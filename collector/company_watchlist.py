from __future__ import annotations

import functools
import json
import re
import ipaddress
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from collector.ats_boards import collect_ats_board, load_ats_boards
from collector.results import source_failed, source_ok
from collector.types import STATUS_DEGRADED, SourceResult
from integrations.http_client import fetch_impersonated, fetch_json, fetch_text, post_form_data, post_json
from parser.normalize import is_target_job

_JOB_URL_TOKENS = ("career", "job", "jobs", "vacanc", "position", "opening")
_ALLOWED_LOCATIONS_BY_COMPANY: dict[str, frozenset[str]] = {
    "zoolatech": frozenset(
        {
            "central europe",
            "eastern europe",
            "europe",
            "remote",
            "ukraine",
        }
    ),
}
_CONSCENSIA_API_URL = "https://careers.conscensia.com/wp-json/wp/v2/job?per_page=100"
_SVITLA_API_URL = "https://svitla.com/career/api/v1/jobs/public?page={page}"
_PLAYRIX_API_URL = "https://playrix.com/api/v1/index.php"
_VALTECH_API_URL = (
    "https://www.valtech.com/joblist/getjsonresult?id=1571&language=en&limit={limit}&offset={offset}"
)
_VALTECH_PAGE_LIMIT = 100
_ADAPTIQ_PAGE_LIMIT = 20
_MOBILUNITY_AJAX_URL = "https://mobilunity.com/wp-admin/admin-ajax.php"
_MOBILUNITY_NONCE_RE = re.compile(r'paramsVacancy\s*=\s*\{[^}]*"nonce"\s*:\s*"([A-Za-z0-9]+)"')
_CAREER_CARD_SELECTORS = {
    "adaptiq.co": ("a.position-card[href]", ".title", ".job-main-description__right p"),
    "careers.eleks.com": ("a.vacancy-item[href]", ".vacancy-item__title", ".vacancy-item__location"),
    "www.devart.com": ("a.vacancies[href]", "h4", ".vacancies-locations__text"),
}


def default_watchlist_path(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parents[1]
    return base / "database" / "dou_service_companies.json"


def load_company_watchlist(path: Path | None = None) -> list[dict[str, Any]]:
    payload = json.loads((path or default_watchlist_path()).read_text(encoding="utf-8"))
    companies = payload.get("companies") if isinstance(payload, dict) else None
    if not isinstance(companies, list):
        raise ValueError("company watchlist must contain a companies list")
    return [company for company in companies if isinstance(company, dict)]


def _is_job_url(url: str) -> bool:
    value = url.lower()
    return any(token in value for token in _JOB_URL_TOKENS)


def _add_candidate(
    candidates: dict[str, tuple[str, str | None, str | None]],
    *,
    title: str,
    url: str,
    base_url: str,
    description: str | None = None,
    location: str | None = None,
    is_job_posting: bool = False,
) -> None:
    normalized_title = " ".join(title.split())
    absolute_url = urljoin(base_url, url.strip())
    if not normalized_title or not absolute_url.startswith(("http://", "https://")):
        return
    if not is_job_posting and not _is_job_url(absolute_url):
        return
    if not (is_target_job(normalized_title, description) or is_target_job(absolute_url)):
        return
    previous = candidates.get(absolute_url)
    if previous and is_job_posting:
        candidates[absolute_url] = (normalized_title, description or previous[1], location or previous[2])
    elif previous is None:
        candidates[absolute_url] = (normalized_title, description, location)


def _local_description(anchor) -> str | None:
    parent = anchor.parent
    if parent is None:
        return None
    job_links = [
        link
        for link in parent.select("a[href]")
        if _is_job_url(urljoin("https://example.invalid", str(link.get("href") or "")))
    ]
    if len(job_links) > 1:
        return None
    return parent.get_text(" ", strip=True) or None


def _local_location(company: str, anchor) -> str | None:
    country = anchor.select_one(".country")
    if country is not None:
        return country.get_text(" ", strip=True) or None
    if company.strip().lower() == "avenga":
        metadata = anchor.find_next_sibling("div", class_=lambda value: value and "mt-1" in value)
        if metadata is not None:
            return metadata.get_text(" ", strip=True) or None
    return None


def _location_is_allowed(company: str, location: str | None) -> bool:
    allowed = _ALLOWED_LOCATIONS_BY_COMPANY.get(company.strip().lower())
    if not allowed or not location:
        return True
    return location.strip().lower() in allowed


def _job_postings(document):
    def entries(value):
        if isinstance(value, list):
            for item in value:
                yield from entries(item)
        elif isinstance(value, dict):
            types = value.get("@type", [])
            if types == "JobPosting" or (isinstance(types, list) and "JobPosting" in types):
                yield value
            yield from entries(value.get("@graph", []))

    for script in document.select('script[type="application/ld+json"]'):
        try:
            yield from entries(json.loads(script.string or ""))
        except (TypeError, ValueError):
            continue


def _posting_location(entry):
    locations = entry.get("jobLocation") or []
    if not isinstance(locations, list):
        locations = [locations]
    labels = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        address = location.get("address") or {}
        if isinstance(address, str):
            labels.append(address)
        elif isinstance(address, dict):
            country = address.get("addressCountry") or ""
            if isinstance(country, dict):
                country = country.get("name") or ""
            label = ", ".join(str(value) for value in (
                address.get("addressLocality"), address.get("addressRegion"), country
            ) if value)
            if label:
                labels.append(label)
    # Remote does not erase a country restriction in the posting.
    if entry.get("jobLocationType") == "TELECOMMUTE":
        restrictions = entry.get("applicantLocationRequirements") or []
        if not isinstance(restrictions, list):
            restrictions = [restrictions]
        labels.extend(str(item["name"]) for item in restrictions
                      if isinstance(item, dict) and item.get("name"))
        labels.append("Remote")
    return " / ".join(dict.fromkeys(labels)) or None


def _same_detail_origin(url, base_url):
    try:
        target, base = urlsplit(url), urlsplit(base_url)
        if target.scheme != "https" or target.username or target.password or not target.hostname:
            return False
        if (target.scheme, target.hostname, target.port) != (base.scheme, base.hostname, base.port):
            return False
        host = target.hostname.lower()
        if host == "localhost" or host.endswith((".localhost", ".local")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


def _matching_detail(title, html, detail_url=""):
    document = BeautifulSoup(html, "lxml")
    def title_key(text):
        return " ".join(re.findall(r"\w+", text.casefold()))

    for entry in _job_postings(document):
        if title_key(str(entry.get("title") or "")) == title_key(title):
            description = str(entry.get("description") or "")
            if is_target_job(title, description):
                return description, _posting_location(entry)
            break
    host = urlsplit(detail_url).hostname
    if host == "adaptiq.co":
        content = document.select_one(".article__wrapper")
    elif host == "careers.eleks.com":
        content = document.select_one(".vacancy")
    else:
        content = document.select_one("main, article")
    if content is None:
        return "", None
    for node in content.select("script, style, nav, footer, form, aside, .form-tabs, [class*='related']"):
        node.decompose()
    heading = content.select_one("h1")
    if heading is None or len(content.select("h1")) != 1:
        return "", None
    heading_text = heading.get_text(" ", strip=True)
    location = None
    if host == "www.devart.com" and urlsplit(detail_url).path.startswith("/vacancies/"):
        # Devart adds the business unit to the detail heading, but not the listing title.
        role = re.sub(r",\s*[^,\s]+(?:\s+[^,\s]+)*\s+BU$", "", heading_text)
        breadcrumb = content.select_one(".vacancies-breadcrumb")
        active = breadcrumb.select_one(".active") if breadcrumb is not None else None
        if (title_key(role) != title_key(title) or active is None
                or title_key(active.get_text(" ", strip=True)) != title_key(heading_text)):
            return "", None
        location_node = content.select_one(".vacancies-location")
        location = location_node.get_text(" ", strip=True) if location_node else None
        content = breadcrumb.parent
    elif title_key(heading_text) != title_key(title):
        return "", None
    return str(content), location


def extract_ios_jobs(company: str, page_url: str, html: str) -> tuple[list[dict[str, Any]], int]:
    document = BeautifulSoup(html, "lxml")
    selectors = _CAREER_CARD_SELECTORS.get(urlsplit(page_url).hostname)
    if selectors:
        return _extract_career_cards(company, page_url, document, selectors)
    candidates: dict[str, tuple[str, str | None, str | None]] = {}
    job_like_links: set[str] = set()

    for anchor in document.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        absolute_url = urljoin(page_url, href)
        if _is_job_url(absolute_url):
            job_like_links.add(absolute_url)
        _add_candidate(
            candidates,
            title=anchor.get_text(" ", strip=True),
            url=href,
            base_url=page_url,
            description=_local_description(anchor),
            location=_local_location(company, anchor),
        )

    for entry in _job_postings(document):
        title = str(entry.get("title") or "")
        url = str(entry.get("url") or page_url)
        description = str(entry.get("description") or "") or None
        job_like_links.add(urljoin(page_url, url))
        _add_candidate(
            candidates, title=title, url=url, base_url=page_url,
            description=description, location=_posting_location(entry), is_job_posting=True,
        )

    jobs = []
    for url, (title, description, location) in candidates.items():
        if not _location_is_allowed(company, location):
            continue
        job = {"company": company, "title": title, "url": url, "source": "company"}
        if description:
            job["description"] = description
        if location:
            job["location"] = location
        jobs.append(job)
    return jobs, len(job_like_links)


def _extract_career_cards(company, page_url, document, selectors):
    card_selector, title_selector, location_selector = selectors
    jobs = {}
    scanned = set()
    for card in document.select(card_selector):
        title_node = card.select_one(title_selector)
        title = title_node.get_text(" ", strip=True) if title_node else ""
        url = urljoin(page_url, card["href"])
        if not title or not _same_detail_origin(url, page_url) or "/vacancies/" not in urlsplit(url).path:
            raise ValueError("Unexpected career card title or URL")
        scanned.add(url)
        if is_target_job(title):
            jobs[url] = {
                "company": company, "title": title, "url": url, "source": "company",
                "location": " / ".join(node.get_text(" ", strip=True)
                                        for node in card.select(location_selector)) or None,
            }
    return list(jobs.values()), len(scanned)


def _collect_adaptiq(company, career_url):
    if career_url != "https://adaptiq.co/careers/":
        raise ValueError("Unexpected Adaptiq career URL")
    html = fetch_text(career_url)
    jobs, scanned, total, page_size = {}, 0, None, None
    errors = []
    for page in range(1, _ADAPTIQ_PAGE_LIMIT + 1):
        try:
            if page > 1:
                html = post_form_data("https://adaptiq.co/wp-admin/admin-ajax.php", {
                    "action": "vacancy_filter", "isStatic": "false", "pag_num": str(page),
                    "post_count": str(page_size), "ajax_type": "load_more",
                }, timeout=15)
            document = BeautifulSoup(html, "lxml")
            container = document.select_one(".position-list__container")
            if container is None:
                raise ValueError("Adaptiq vacancy container missing")
            page_total = int(container["data-all-posts-count"])
            current = int(container["data-current-posts-count"])
            page_jobs, page_scanned = extract_ios_jobs(company, career_url, str(container))
            if page == 1:
                total = page_total
                listing = document.select_one(".position-list[data-post-count]")
                page_size = int(listing["data-post-count"]) if listing else 0
            # Load-more responses repeat earlier cards; their count must advance to the declared total.
            if (page_total != total or not 0 <= current <= total or current != page_scanned
                    or not 1 <= page_size <= 100 or (page > 1 and current <= scanned)):
                raise ValueError("Adaptiq pagination counts are inconsistent")
            jobs.update((job["url"], job) for job in page_jobs)
            scanned = current
            if scanned == total:
                break
        except Exception as error:  # noqa: BLE001
            if page == 1:
                raise
            errors.append(f"Adaptiq page {page}: {error}")
            break
    else:
        errors.append(f"Adaptiq pagination limit: scanned {scanned} of {total}")
    return list(jobs.values()), scanned, errors


def _mobilunity_cards(company: str, page_url: str, document) -> list[dict[str, Any]]:
    # Filter/tag chips on this page all share the listing's own URL (a site bug, not JS-rendered
    # variation), so scoping to real cards -- rather than walking every <a> -- is what keeps them out.
    jobs = []
    for card in document.select("div.one-vacancy"):
        anchor = card.select_one("h5.svacancy-name a[href]")
        if anchor is None:
            continue
        title = anchor.get_text(" ", strip=True)
        url = urljoin(page_url, str(anchor["href"]))
        path = urlsplit(url).path
        if (
            not title
            or urlsplit(url).hostname != "mobilunity.com"
            or not path.startswith("/vacancy/")
            or path == "/vacancy/"
        ):
            continue
        description_node = card.select_one(".svacancy-excerpt")
        description = (description_node.get_text(" ", strip=True) if description_node else None) or None
        if not is_target_job(title, description):
            continue
        location_node = card.select_one(".vacancy-country img[alt]")
        jobs.append({
            "company": company, "title": title, "url": url, "source": "company",
            "description": description,
            "location": (str(location_node["alt"]).strip() if location_node else None) or None,
        })
    return jobs


def _collect_mobilunity(company: str, career_url: str) -> tuple[list[dict[str, Any]], int, list[str]]:
    if career_url != "http://mobilunity.com/vacancy/":
        raise ValueError("Unexpected Mobilunity vacancies URL")
    html = fetch_text(career_url)
    document = BeautifulSoup(html, "lxml")
    wrap = document.select_one(".vacancies-wrap[data-max]")
    if wrap is None:
        raise ValueError("Mobilunity vacancies wrap missing")
    max_pages = int(wrap["data-max"])
    nonce_match = _MOBILUNITY_NONCE_RE.search(html)
    if nonce_match is None:
        raise ValueError("Mobilunity ajax nonce missing")
    nonce = nonce_match.group(1)

    jobs: dict[str, dict[str, Any]] = {}
    scanned = len(document.select("div.one-vacancy"))
    for job in _mobilunity_cards(company, career_url, document):
        jobs[job["url"]] = job

    errors: list[str] = []
    for page in range(2, max_pages + 1):
        try:
            fragment = post_form_data(_MOBILUNITY_AJAX_URL, {
                "action": "vacancyFilter", "nonce": nonce, "current_page": str(page),
                "filter": "", "search": "",
            })
        except Exception as error:  # noqa: BLE001
            errors.append(f"Mobilunity page {page}: {error}")
            continue
        page_document = BeautifulSoup(fragment, "lxml")
        scanned += len(page_document.select("div.one-vacancy"))
        for job in _mobilunity_cards(company, career_url, page_document):
            jobs[job["url"]] = job
    return list(jobs.values()), scanned, errors


def _collect_conscensia(company: str) -> tuple[list[dict[str, Any]], int]:
    try:
        payload = fetch_json(_CONSCENSIA_API_URL)
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else 0
        if status not in {403, 429, 454}:
            raise
        payload = json.loads(fetch_impersonated(_CONSCENSIA_API_URL))
    if not isinstance(payload, list):
        raise RuntimeError("Conscensia API returned an unexpected payload")
    items = payload
    jobs: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title_node = item.get("title")
        title = str(title_node.get("rendered") or "") if isinstance(title_node, dict) else ""
        content = item.get("content") or ""
        description = str(content.get("rendered") or "") if isinstance(content, dict) else str(content)
        if not is_target_job(title, description):
            continue
        jobs.append(
            {
                "company": company,
                "title": title,
                "url": str(item.get("link") or ""),
                "source": "company",
                "source_job_id": str(item.get("id") or ""),
                "description": description or None,
            }
        )
    return jobs, len(items)


def _collect_svitla(company: str) -> tuple[list[dict[str, Any]], int]:
    jobs: list[dict[str, Any]] = []
    scanned = 0
    page = 1
    while True:
        payload = fetch_json(_SVITLA_API_URL.format(page=page))
        if not isinstance(payload, dict):
            raise RuntimeError("Svitla API returned an unexpected payload")
        items = payload.get("items")
        if not isinstance(items, list):
            raise RuntimeError("Svitla API payload is missing items")
        scanned += len(items)
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("position") or "").strip()
            description = str(item.get("fullDescription") or "")
            if not is_target_job(title, description):
                continue
            cities = item.get("jobCities") if isinstance(item.get("jobCities"), list) else []
            locations = []
            for entry in cities:
                city = entry.get("city") if isinstance(entry, dict) else None
                if not isinstance(city, dict):
                    continue
                label = ", ".join(
                    part
                    for part in (str(city.get("name") or "").strip(), str(city.get("country") or "").strip())
                    if part and part.lower() != "any city"
                )
                if label:
                    locations.append(label)
            slug = str(item.get("slug") or "").strip()
            jobs.append(
                {
                    "company": company,
                    "title": title,
                    "url": urljoin("https://svitla.com/career/job/", slug),
                    "source": "company",
                    "source_job_id": str(item.get("id") or ""),
                    "location": " / ".join(dict.fromkeys(locations)) or None,
                    "description": description or None,
                }
            )
        total_pages = int(payload.get("pages") or 1)
        if page >= total_pages:
            break
        page += 1
    return jobs, scanned


def _collect_label_your_data(company: str) -> tuple[list[dict[str, Any]], int]:
    # Kept as a watchlist branch rather than a company_ats_boards.json entry so
    # the source id, and with it the health history, stays unchanged.
    return collect_ats_board(company, {"ats": "workable", "token": "labelyourdata"})


def _playrix_payload(action: str) -> dict[str, Any]:
    payload = post_json(
        _PLAYRIX_API_URL,
        {"action": action, "options": {"lang": "en"}},
        params={"action": action},
    )
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise RuntimeError(f"Playrix API failed for {action}")
    return payload


def _collect_valtech(company: str) -> tuple[list[dict[str, Any]], int]:
    jobs: list[dict[str, Any]] = []
    scanned = 0
    offset = 0
    while True:
        payload = fetch_json(
            _VALTECH_API_URL.format(limit=_VALTECH_PAGE_LIMIT, offset=offset)
        )
        if not isinstance(payload, dict):
            raise RuntimeError("Valtech API returned an unexpected payload")
        items = payload.get("list")
        page = payload.get("page") if isinstance(payload.get("page"), dict) else {}
        if not isinstance(items, list):
            raise RuntimeError("Valtech API payload is missing list")
        scanned += len(items)
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not is_target_job(title):
                continue
            offices = item.get("offices") if isinstance(item.get("offices"), list) else []
            location = " / ".join(
                str(office).strip() for office in offices if str(office).strip()
            )
            relative_url = str(item.get("url") or "").strip()
            jobs.append(
                {
                    "company": company,
                    "title": title,
                    "url": urljoin("https://www.valtech.com", relative_url),
                    "source": "company",
                    "source_job_id": str(item.get("id") or ""),
                    "location": location or None,
                }
            )
        item_total = int(page.get("itemTotal") or 0)
        offset += len(items)
        if not items or offset >= item_total:
            break
    return jobs, scanned


def _collect_playrix(company: str) -> tuple[list[dict[str, Any]], int]:
    jobs_payload = _playrix_payload("job/getList")
    sections_payload = _playrix_payload("job/getSectionList")
    items = jobs_payload.get("items")
    sections = sections_payload.get("items")
    if not isinstance(items, list) or not isinstance(sections, list):
        raise RuntimeError("Playrix API payload is missing items")
    section_codes = {
        item.get("id"): str(item.get("code") or "")
        for item in sections
        if isinstance(item, dict)
    }
    visible_items = [
        item for item in items if isinstance(item, dict) and item.get("isHidden") is not True
    ]
    jobs: list[dict[str, Any]] = []
    for item in visible_items:
        title = str(item.get("name") or "").strip()
        description = " ".join(
            str(item.get(field) or "")
            for field in (
                "previewText",
                "detailText",
                "responsibilities",
                "requirements",
                "ourStack",
            )
        )
        if not is_target_job(title, description):
            continue
        section = section_codes.get(item.get("parentId"), "")
        slug = str(item.get("code") or "").strip()
        if not section or not slug:
            raise RuntimeError("Playrix job is missing its URL components")
        jobs.append(
            {
                "company": company,
                "title": title,
                "url": f"https://playrix.com/job/open/{section}/{slug}",
                "source": "company",
                "source_job_id": str(item.get("id") or ""),
                "description": description or None,
                "remote": str(item.get("workFormat") or "unknown"),
            }
        )
    return jobs, len(visible_items)


@functools.cache
def _ats_boards() -> dict[str, dict[str, str]]:
    return load_ats_boards()


def collect_watchlist_company(company: dict[str, Any]) -> SourceResult:
    name = str(company.get("name") or "Unknown company").strip()
    slug = str(company.get("slug") or name.lower()).strip()
    career_url = str(company.get("career_url") or "").strip()
    source_id = f"company-watchlist:{slug}"
    started = time.perf_counter()
    if not career_url:
        fallback_url = str(company.get("company_site_url") or company.get("dou_company_url") or "")
        return source_failed(
            name,
            fallback_url,
            "official career URL unresolved",
            started,
            source_id=source_id,
        )
    try:
        board = _ats_boards().get(slug)
        if board is not None:
            jobs, scanned = collect_ats_board(name, board)
            # API postings and page links are different units, so health history starts fresh.
            return source_ok(name, career_url, jobs, started, scanned=scanned, source_id=f"company-ats:{slug}")
        if slug == "conscensia":
            jobs, scanned = _collect_conscensia(name)
            return source_ok(name, career_url, jobs, started, scanned=scanned, source_id=source_id)
        if slug == "svitla-systems-inc":
            jobs, scanned = _collect_svitla(name)
            return source_ok(name, career_url, jobs, started, scanned=scanned, source_id=source_id)
        if slug == "label-your-data":
            jobs, scanned = _collect_label_your_data(name)
            return source_ok(name, career_url, jobs, started, scanned=scanned, source_id=source_id)
        if slug == "playrix":
            jobs, scanned = _collect_playrix(name)
            return source_ok(name, career_url, jobs, started, scanned=scanned, source_id=source_id)
        if slug == "valtech":
            jobs, scanned = _collect_valtech(name)
            return source_ok(name, career_url, jobs, started, scanned=scanned, source_id=source_id)
        errors = []
        if slug == "adaptiq":
            jobs, scanned, errors = _collect_adaptiq(name, career_url)
        elif slug == "mobilunity":
            jobs, scanned, errors = _collect_mobilunity(name, career_url)
        else:
            try:
                html = fetch_text(career_url)
            except requests.HTTPError as error:
                status = error.response.status_code if error.response is not None else 0
                if status not in {403, 429}:
                    raise
                html = fetch_impersonated(career_url)
            jobs, scanned = extract_ios_jobs(name, career_url, html)
        result = source_ok(
            name,
            career_url,
            jobs,
            started,
            scanned=scanned,
            source_id=source_id,
        )
        if errors:
            result.status = STATUS_DEGRADED
            result.error = "; ".join(errors)
        return result
    except Exception as error:  # noqa: BLE001
        return source_failed(name, career_url, error, started, source_id=source_id)
