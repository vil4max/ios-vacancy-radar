from __future__ import annotations

import html as html_lib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urljoin

from collector.generic import absolute_url, title_from_slug
from collector.company_watchlist import _matching_detail
from collector.results import source_failed, source_ok
from collector.types import STATUS_DEGRADED, STATUS_FAILED, SourceResult
from integrations.http_client import (
    fetch_impersonated,
    fetch_json,
    fetch_text,
    fetch_text_allowing_bot_wall,
    post_form_data,
)
from contextlib import contextmanager

from parser.normalize import is_target_job

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)
_RBI_MAX_DETAIL_PAGES = 60
_RBI_MAX_WORKERS = 6
_IMPERSONATE_CANDIDATES = ("chrome136", "chrome131", "chrome124", "safari184", "firefox135")
_ZONE3000_API_URL = "https://zone3000.net/api/vacancies"
_ZONE3000_HOME_URL = "https://zone3000.net/"
_ZONE3000_LIST_URL = "https://zone3000.net/vacancies"
_SOFTSERVE_LIST_URL = "https://career.softserveinc.com/en-us/vacancies"
_SOFTSERVE_PAYLOAD_URL = "https://career.softserveinc.com/en-us/vacancies/_payload.json"
_SOFTSERVE_API_URL = "https://career.softserveinc.com/api/frontend/vacancies"
_SOFTSERVE_MAX_PAGES = 40


def _fetch_zone3000_api_text() -> str:
    return fetch_impersonated(
        _ZONE3000_API_URL,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Referer": _ZONE3000_LIST_URL,
        },
        warm_urls=(_ZONE3000_HOME_URL, _ZONE3000_LIST_URL),
        accept=lambda text: text.lstrip().startswith("["),
    )


def _fetch_softserve_vacancies() -> list[dict[str, Any]]:
    from curl_cffi import requests as curl_requests

    last_error: Exception | None = None
    for impersonate in _IMPERSONATE_CANDIDATES:
        try:
            session = curl_requests.Session(impersonate=impersonate)
            warm = session.get(
                _SOFTSERVE_PAYLOAD_URL,
                headers={
                    "Accept": "application/json",
                    "Referer": _SOFTSERVE_LIST_URL,
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=30,
            )
            if warm.status_code >= 400:
                last_error = RuntimeError(
                    f"HTTP {warm.status_code} warming SoftServe session"
                )
                continue

            items: list[dict[str, Any]] = []
            page = 1
            last_page = 1
            while page <= last_page and page <= _SOFTSERVE_MAX_PAGES:
                response = session.get(
                    _SOFTSERVE_API_URL,
                    params={"query": "*?", "page": page},
                    headers={
                        "Accept": "application/json, text/plain, */*",
                        "Referer": _SOFTSERVE_LIST_URL,
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                    timeout=30,
                )
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"HTTP {response.status_code} for SoftServe vacancies page {page}"
                    )
                payload = response.json()
                data = (
                    payload.get("data")
                    if isinstance(payload.get("data"), dict)
                    else payload
                )
                vacancies = data.get("vacancies") if isinstance(data, dict) else None
                if not isinstance(vacancies, list):
                    raise RuntimeError("SoftServe API missing vacancies list")
                items.extend(item for item in vacancies if isinstance(item, dict))
                meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
                try:
                    last_page = max(1, int(meta.get("last_page") or page))
                except (TypeError, ValueError):
                    last_page = page
                page += 1
            return items
        except Exception as error:  # noqa: BLE001
            last_error = error
    raise RuntimeError(
        str(last_error) if last_error else "failed to fetch SoftServe vacancies"
    )


def _ok(
    company: str,
    source_url: str,
    jobs: list[dict[str, Any]],
    started: float,
    *,
    scanned: int | None = None,
    empty_is_healthy: bool = False,
) -> SourceResult:
    return source_ok(
        company,
        source_url,
        jobs,
        started,
        scanned=scanned,
        empty_is_healthy=empty_is_healthy,
    )


def _fail(company: str, source_url: str, error: Exception, started: float) -> SourceResult:
    return source_failed(company, source_url, error, started)


def collect_andersen() -> SourceResult:
    company = "Andersen"
    started = time.perf_counter()
    url = "https://asite-api.andersenlab.com/api/integration/recruitment/vacancies"
    try:
        payload = fetch_json(
            url,
            headers={
                "Accept-Language": "en",
                "Accept": "application/json",
                "Referer": "https://people.andersenlab.com/",
            },
        )
        items = payload if isinstance(payload, list) else payload.get("vacancies", payload.get("data", []))
        if not isinstance(items, list):
            items = []
        jobs: list[dict[str, Any]] = []
        for item in items:
            title = str(item.get("name") or item.get("title") or "")
            technologies = item.get("technologies") or []
            tech_text = " ".join(str(t) for t in technologies)
            if not (is_target_job(title) or is_target_job(tech_text)):
                continue
            vacancy_id = item.get("vacancy_id") or item.get("id")
            if not vacancy_id:
                continue
            jobs.append(
                {
                    "company": company,
                    "title": title or tech_text,
                    "url": f"https://people.andersenlab.com/vacancy/{vacancy_id}",
                    "source": "company",
                    "source_job_id": str(vacancy_id),
                }
            )
        return _ok(company, url, jobs, started, scanned=len(items))
    except Exception as error:  # noqa: BLE001
        return _fail(company, url, error, started)


def collect_onix() -> SourceResult:
    company = "Onix Systems"
    started = time.perf_counter()
    list_url = "https://onix-systems.com/careers"
    try:
        html = fetch_text(list_url)
        match = _NEXT_DATA.search(html)
        if not match:
            return _ok(company, list_url, [], started)
        payload = json.loads(match.group(1))
        career_list = (
            payload.get("props", {})
            .get("pageProps", {})
            .get("careerList", [])
        )
        if not isinstance(career_list, list):
            career_list = []
        jobs: list[dict[str, Any]] = []
        for entry in career_list:
            attributes = entry.get("attributes") if isinstance(entry, dict) else None
            if not isinstance(attributes, dict):
                continue
            title = str(attributes.get("name") or "")
            if not is_target_job(title):
                continue
            slug = attributes.get("url") or ""
            canonical = attributes.get("canonical")
            job_url = str(canonical) if canonical else f"https://onix-systems.com/careers/{slug}"
            jobs.append({"company": company, "title": title, "url": job_url, "source": "company"})
        return _ok(company, list_url, jobs, started, scanned=len(career_list))
    except Exception as error:  # noqa: BLE001
        return _fail(company, list_url, error, started)


def collect_nortal() -> SourceResult:
    company = "Nortal"
    started = time.perf_counter()
    url = "https://nortal.career.page/api/jobs?location=Ukraine"
    try:
        payload = fetch_json(url)
        items = payload.get("jobs", []) if isinstance(payload, dict) else []
        jobs: list[dict[str, Any]] = []
        for item in items:
            data = item.get("data") if isinstance(item, dict) else None
            if not isinstance(data, dict):
                continue
            title = str(data.get("title") or "")
            if not is_target_job(title):
                continue
            job_url = str(data.get("apply_url") or data.get("url") or "")
            if not job_url:
                continue
            jobs.append(
                {
                    "company": company,
                    "title": title,
                    "url": job_url,
                    "source": "company",
                    "location": "Ukraine",
                }
            )
        return _ok(company, url, jobs, started, scanned=len(items))
    except Exception as error:  # noqa: BLE001
        return _fail(company, url, error, started)


def collect_ciklum() -> SourceResult:
    company = "Ciklum"
    started = time.perf_counter()
    url = (
        "https://ialmme.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/"
        "recruitingCEJobRequisitions?onlyData=true&expand=requisitionList"
        "&finder=findReqs;siteNumber=CX_1001,keyword=ios,limit=50,offset=0"
    )
    query_errors: list[str] = []
    try:
        payload = fetch_json(url)
        items = payload.get("items") or []
        requisitions = []
        if items and isinstance(items[0], dict):
            requisitions = list(items[0].get("requisitionList") or [])
        jobs: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for item in requisitions:
            title = str(item.get("Title") or "")
            if not is_target_job(title):
                continue
            job_id = item.get("Id")
            if not job_id or str(job_id) in seen_ids:
                continue
            seen_ids.add(str(job_id))
            jobs.append(
                {
                    "company": company,
                    "title": title,
                    "url": f"https://explore-jobs.ciklum.com/en/sites/ciklum-career/job/{job_id}",
                    "source": "company",
                    "source_job_id": str(job_id),
                }
            )
        return _partial_result(_ok(company, url, jobs, started, scanned=len(requisitions)), query_errors)
    except Exception as error:  # noqa: BLE001
        return _fail(company, url, error, started)


def collect_sigma() -> SourceResult:
    company = "Sigma Software"
    started = time.perf_counter()
    endpoint = "https://career.sigma.software/wp-admin/admin-ajax.php"
    query_errors: list[str] = []
    try:
        from bs4 import BeautifulSoup

        jobs: list[dict[str, Any]] = []
        scanned: set[str] = set()
        emitted: set[str] = set()

        def sweep(keyword: str) -> None:
            page = 1
            while page <= 20:
                fields = {
                    "action": "filter_vacancies_v2" if page == 1 else "filter_vacancies_v2_loadmore",
                    "keyword": keyword,
                    "direction": '["engineering"]',
                    "direction_type": "parent",
                    "locations": "[]",
                    "seniority": "[]",
                    "workplace_type": "[]",
                }
                if page > 1:
                    fields["page"] = str(page - 1)
                raw = post_form_data(endpoint, fields)
                payload = json.loads(raw)
                if not payload.get("success"):
                    break
                data = payload.get("data") or {}
                html = data.get("html") or ""
                document = BeautifulSoup(html, "lxml")
                for card in document.select("a.vacancy-card-new"):
                    href = card.get("href") or ""
                    if not href:
                        continue
                    absolute = absolute_url(href, "https://career.sigma.software/")
                    if absolute in emitted:
                        continue
                    scanned.add(absolute)
                    title_node = card.select_one("h3.vacancy-card-new__title")
                    title = ""
                    if title_node is not None:
                        title = title_node.get_text(strip=True)
                    tech_nodes = card.select("div.vacancy-card-new__technologies span")
                    tech_text = " ".join(node.get_text(strip=True) for node in tech_nodes)
                    if not (is_target_job(title) or is_target_job(tech_text)):
                        continue
                    job = {
                        "company": company,
                        "title": title or tech_text,
                        "url": absolute,
                        "source": "company",
                        "description": tech_text or None,
                    }
                    jobs.append(job)
                    emitted.add(absolute)
                if not data.get("has_more"):
                    break
                page += 1

        sweep("")
        return _partial_result(_ok(company, endpoint, jobs, started, scanned=len(scanned)), query_errors)
    except Exception as error:  # noqa: BLE001
        return _fail(company, endpoint, error, started)


def collect_dataart() -> SourceResult:
    company = "DataArt"
    started = time.perf_counter()
    url = (
        "https://www.dataart.team/dataart-team/api/vacancies/"
        "filter-fields-page?categories=569"
    )
    query_errors: list[str] = []
    try:
        payload = fetch_json(url)
        items = (
            payload.get("vacancies", {}).get("items")
            if isinstance(payload.get("vacancies"), dict)
            else payload.get("items", [])
        )
        if not isinstance(items, list):
            items = []
        items = list(items)
        with _secondary_query(query_errors, "all categories"):
            extra = fetch_json(url.partition("?")[0])
            extra_items = extra.get("vacancies", {}).get("items") if isinstance(extra.get("vacancies"), dict) else extra.get("items", [])
            if isinstance(extra_items, list):
                items.extend(extra_items)
        jobs: list[dict[str, Any]] = []
        emitted: set[str] = set()
        for item in items:
            title = str(item.get("title") or "")
            slug = item.get("slug")
            if not is_target_job(title) or not slug or slug in emitted:
                continue
            emitted.add(slug)
            jobs.append(
                {
                    "company": company,
                    "title": title,
                    "url": f"https://www.dataart.team/vacancies/{slug}",
                    "source": "company",
                }
            )
        return _partial_result(_ok(company, url, jobs, started, scanned=len(items)), query_errors)
    except Exception as error:  # noqa: BLE001
        return _fail(company, url, error, started)


def collect_grid_dynamics() -> SourceResult:
    company = "Grid Dynamics"
    started = time.perf_counter()
    list_url = "https://www.griddynamics.com/careers/discover-openings"
    try:
        html = fetch_text(list_url)
        match = re.search(r"data-vacancies='([^']+)'", html)
        if not match:
            return _ok(company, list_url, [], started)
        vacancies = json.loads(html_lib.unescape(match.group(1)))
        if not isinstance(vacancies, list):
            vacancies = []
        jobs: list[dict[str, Any]] = []
        for vacancy in vacancies:
            title = str(vacancy.get("title") or "")
            if not is_target_job(title):
                continue
            locations = []
            for loc in vacancy.get("countryLocations") or []:
                city = loc.get("city") or ""
                country = loc.get("country") or ""
                label = ", ".join(part for part in (city, country) if part)
                if label:
                    locations.append(label)
            for related in vacancy.get("relatedLocations") or []:
                if isinstance(related, str) and related.strip():
                    locations.append(related.strip())
            location = " / ".join(locations) if locations else None
            vacancy_id = vacancy.get("id")
            if not vacancy_id:
                continue
            jobs.append(
                {
                    "company": company,
                    "title": title,
                    "url": f"https://www.griddynamics.com/careers/vacancy/{vacancy_id}",
                    "source": "company",
                    "location": location,
                    "source_job_id": str(vacancy_id),
                }
            )
        return _ok(company, list_url, jobs, started, scanned=len(vacancies))
    except Exception as error:  # noqa: BLE001
        return _fail(company, list_url, error, started)


def _rbi_page(url: str) -> dict[str, Any]:
    from bs4 import BeautifulSoup

    page = fetch_text(url)
    document = BeautifulSoup(page, "lxml")
    node = document.select_one('meta[property="og:title"]')
    title = ""
    if node is not None:
        title = str(node.get("content") or "")
    if not title:
        node = document.select_one("h1, title")
        if node is not None:
            title = node.get_text(" ", strip=True)
    title = re.sub(r"^Vacancy\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+—\s+RBI Retail Innovation\s*$", "", title)
    title = html_lib.unescape(title).strip()
    if not title or title.casefold() in {"careers", "career", "vacancies", "rbi retail innovation", "кар’єра", "кар\'єра", "вакансії"}:
        raise ValueError("RBI detail has no verified title")
    description, location = _matching_detail(title, page)
    return {"company": "RBI Retail Innovation", "title": title, "url": url,
            "source": "company", "description": description or None, "location": location}


def _rbi_title(url: str) -> str | None:
    try:
        return _rbi_page(url)["title"]
    except Exception:  # noqa: BLE001
        return None


def collect_rbi() -> SourceResult:
    company = "RBI Retail Innovation"
    started = time.perf_counter()
    list_url = "https://www.rbi-ri.com.ua/career"
    sitemap_url = "https://www.rbi-ri.com.ua/sitemap.xml"
    errors: list[str] = []
    urls: list[str] = []
    discovery_success = 0
    for endpoint in (sitemap_url, list_url):
        try:
            page = fetch_text(endpoint)
            discovery_success += 1
            for match in re.finditer(
                r"https?://(?:www\.)?rbi-ri\.com\.ua/career/([a-z0-9-]+)",
                page, re.IGNORECASE,
            ):
                url = f"https://www.rbi-ri.com.ua/career/{match.group(1)}"
                if url not in urls:
                    urls.append(url)
        except Exception as error:  # noqa: BLE001
            errors.append(f"{endpoint}: {error}")
    if not discovery_success:
        return _fail(company, list_url, RuntimeError("; ".join(errors)), started)
    if len(urls) > _RBI_MAX_DETAIL_PAGES:
        errors.append(f"RBI detail limit: {len(urls) - _RBI_MAX_DETAIL_PAGES} deferred")
    urls = urls[:_RBI_MAX_DETAIL_PAGES]

    def detail(url):
        try:
            return _rbi_page(url), None
        except Exception as error:  # noqa: BLE001
            return None, f"RBI detail {url}: {error}"

    with ThreadPoolExecutor(max_workers=_RBI_MAX_WORKERS) as pool:
        pages = list(pool.map(detail, urls))
    jobs = []
    verified = 0
    for job, error in pages:
        if error:
            errors.append(error)
            continue
        verified += 1
        if not is_target_job(job["title"], job.get("description")):
            continue
        jobs.append(job)
    result = _ok(company, list_url, jobs, started, scanned=len(urls))
    if errors:
        result.status = STATUS_FAILED if urls and not verified else STATUS_DEGRADED
        result.error = "; ".join(errors)
    return result


def collect_nix_html() -> SourceResult:
    company = "N-iX"
    started = time.perf_counter()
    list_url = (
        "https://careers.n-ix.com/jobs/"
        "?keyword=ios&work_type%5B%5D=Remote&work_type%5B%5D=Office+based"
    )
    query_errors: list[str] = []
    try:
        html = fetch_text(list_url)
        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        pattern = re.compile(
            r'<a[^>]+href="([^"]+)"[^>]*>\s*([^<]+\(#\d+\))\s*</a>',
            re.IGNORECASE | re.DOTALL,
        )
        for match in pattern.finditer(html):
            job_url = absolute_url(match.group(1), "https://careers.n-ix.com/")
            title = match.group(2).strip()
            if job_url in seen:
                continue
            seen.add(job_url)
            if not is_target_job(title):
                continue
            jobs.append({"company": company, "title": title, "url": job_url, "source": "company"})
        return _partial_result(_ok(company, list_url, jobs, started, scanned=len(seen)), query_errors)
    except Exception as error:  # noqa: BLE001
        return _fail(company, list_url, error, started)


def collect_intellias() -> SourceResult:
    company = "Intellias"
    started = time.perf_counter()
    list_url = "https://career.intellias.com/?s=iOS"
    query_errors: list[str] = []
    try:
        html = fetch_text(list_url)
        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        pattern = re.compile(
            r'<a[^>]+href="(https://career\.intellias\.com/vacancy/[^"]+)"[^>]*>([^<]{5,120})</a>',
            re.IGNORECASE,
        )
        for match in pattern.finditer(html):
            job_url = match.group(1)
            title = match.group(2).strip()
            if job_url in seen:
                continue
            seen.add(job_url)
            if not is_target_job(title):
                continue
            jobs.append({"company": company, "title": title, "url": job_url, "source": "company"})
        return _partial_result(_ok(company, list_url, jobs, started, scanned=len(seen)), query_errors)
    except Exception as error:  # noqa: BLE001
        return _fail(company, list_url, error, started)


def collect_infopulse() -> SourceResult:
    company = "Infopulse"
    started = time.perf_counter()
    list_url = "https://careers.tieto.com/jobs?q=iOS"
    query_errors: list[str] = []
    try:
        html = fetch_text(list_url)
        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        pattern = re.compile(
            r'<a[^>]+href="(/job/[^"]+)"[^>]*>([^<]{5,120})</a>',
            re.IGNORECASE,
        )
        for match in pattern.finditer(html):
            title = match.group(2).strip()
            if title.lower() == "apply":
                continue
            job_url = urljoin("https://careers.tieto.com/", match.group(1))
            if job_url in seen:
                continue
            seen.add(job_url)
            if not is_target_job(title):
                continue
            jobs.append({"company": company, "title": title, "url": job_url, "source": "company"})
        return _partial_result(_ok(company, list_url, jobs, started, scanned=len(seen)), query_errors)
    except Exception as error:  # noqa: BLE001
        return _fail(company, list_url, error, started)


def collect_softserve() -> SourceResult:
    company = "SoftServe"
    started = time.perf_counter()
    try:
        items = _fetch_softserve_vacancies()
        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            title = str(item.get("name") or "").strip()
            slug = str(item.get("urlSegment") or "").strip().lstrip("/")
            if not title or not slug:
                continue
            job_url = f"{_SOFTSERVE_LIST_URL.rstrip('/')}/{slug}"
            if job_url in seen:
                continue
            seen.add(job_url)
            if not is_target_job(title):
                continue
            location = str(item.get("city") or "").strip() or None
            jobs.append(
                {
                    "company": company,
                    "title": title,
                    "url": job_url,
                    "source": "company",
                    "source_job_id": str(item.get("id")) if item.get("id") is not None else None,
                    "location": location,
                }
            )
        return _ok(company, _SOFTSERVE_LIST_URL, jobs, started, scanned=len(items))
    except Exception as error:  # noqa: BLE001
        return _fail(company, _SOFTSERVE_LIST_URL, error, started)


def collect_globallogic() -> SourceResult:
    company = "GlobalLogic"
    started = time.perf_counter()
    list_url = "https://www.globallogic.com/ua/career-search-page/?keywords=ios"
    query_errors: list[str] = []
    try:
        from bs4 import BeautifulSoup

        html = fetch_text_allowing_bot_wall(list_url)
        if html is None:
            html = fetch_impersonated(list_url)
        document = BeautifulSoup(html, "lxml")
        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for anchor in document.select("a.job_box[href*='/ua/careers/']"):
            href = anchor.get("href") or ""
            if "-irc" not in href.lower():
                continue
            absolute = absolute_url(href, "https://www.globallogic.com/")
            if absolute in seen:
                continue
            seen.add(absolute)
            heading = anchor.select_one("h4")
            title = heading.get_text(strip=True) if heading else anchor.get_text(" ", strip=True)
            title = re.sub(r"\s+IRC\d+\s*$", "", title).strip()
            if not is_target_job(title):
                continue
            locations = [node.get_text(" ", strip=True) for node in anchor.select(".job_location")]
            work_modes = [node.get_text(" ", strip=True) for node in anchor.select(".job_tag")]
            jobs.append(
                {
                    "company": company,
                    "title": title,
                    "url": absolute,
                    "source": "company",
                    "location": ", ".join(dict.fromkeys(filter(None, locations))) or None,
                    "remote": " ".join(dict.fromkeys(filter(None, work_modes))) or None,
                }
            )

        if not jobs:
            for match in re.finditer(
                r"https://www\.globallogic\.com/ua/careers/[a-z0-9-]+-irc\d+/?",
                html,
                re.IGNORECASE,
            ):
                absolute = match.group(0)
                if absolute in seen:
                    continue
                seen.add(absolute)
                title = title_from_slug(absolute)
                title = re.sub(r"\s*irc\d+\s*$", "", title, flags=re.IGNORECASE).strip()
                if not is_target_job(title):
                    continue
                jobs.append({"company": company, "title": title, "url": absolute, "source": "company"})
        return _partial_result(_ok(company, list_url, jobs, started, scanned=len(seen)), query_errors)
    except Exception as error:  # noqa: BLE001
        return _fail(company, list_url, error, started)


def _luxoft_location(anchor: Any) -> str | None:
    bookmark = anchor.select_one("[data-job]")
    raw_meta = bookmark.get("data-job") if bookmark is not None else None
    if raw_meta:
        try:
            meta = json.loads(str(raw_meta))
        except json.JSONDecodeError:
            meta = None
        if isinstance(meta, dict):
            city = str(meta.get("city") or "").strip()
            country = str(meta.get("location") or "").strip()
            label = ", ".join(part for part in (city, country) if part)
            if label:
                return label
    loc_el = anchor.select_one('[class*="location"]')
    if loc_el is None:
        return None
    text = loc_el.get_text(" ", strip=True)
    return text or None


_LUXOFT_COUNTRY_CODES = {
    "MY": "Malaysia",
    "IN": "India",
    "EG": "Egypt",
    "PL": "Poland",
    "UA": "Ukraine",
    "DE": "Germany",
    "RO": "Romania",
    "BG": "Bulgaria",
    "PT": "Portugal",
    "MX": "Mexico",
    "US": "United States",
    "GB": "United Kingdom",
    "UK": "United Kingdom",
}


def _luxoft_location_from_detail(job_url: str) -> str | None:
    try:
        html = fetch_text(job_url)
    except Exception:  # noqa: BLE001
        return None
    from bs4 import BeautifulSoup

    document = BeautifulSoup(html, "lxml")
    for script in document.select('script[type="application/ld+json"]'):
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        nodes = payload if isinstance(payload, list) else [payload]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if str(node.get("@type") or "") != "JobPosting":
                continue
            place = node.get("jobLocation")
            if isinstance(place, list):
                place = place[0] if place else None
            if not isinstance(place, dict):
                continue
            address = place.get("address")
            if not isinstance(address, dict):
                continue
            city = str(address.get("addressLocality") or "").strip()
            country_raw = str(address.get("addressCountry") or "").strip()
            country = _LUXOFT_COUNTRY_CODES.get(country_raw.upper(), country_raw)
            label = ", ".join(part for part in (city, country) if part)
            if label:
                return label
    return None


def collect_luxoft() -> SourceResult:
    company = "Luxoft"
    started = time.perf_counter()
    list_url = (
        "https://career.luxoft.com/jobs"
        "?specialization=iOS+%28Objective-C%2FSwift%29"
    )
    query_errors: list[str] = []
    try:
        from bs4 import BeautifulSoup

        html = fetch_text(list_url)
        with _secondary_query(query_errors, "all specializations"):
            html += "\n" + fetch_text(list_url.partition("?")[0])
        document = BeautifulSoup(html, "lxml")
        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for anchor in document.select('a[href*="/jobs/"]'):
            href = str(anchor.get("href") or "")
            if not re.search(r"/jobs/[a-z0-9-]+-\d+/?", href, re.IGNORECASE):
                continue
            absolute = absolute_url(href, "https://career.luxoft.com/")
            if absolute in seen:
                continue
            seen.add(absolute)
            heading = anchor.select_one("h2")
            title = heading.get_text(" ", strip=True) if heading is not None else ""
            raw = anchor.get_text(" ", strip=True)
            if not title:
                title = re.split(r"\s+Facebook\s+", raw, maxsplit=1)[0].strip()
                title = re.sub(
                    r"\s+iOS\s*\(Objective-C/Swift\).*$",
                    "",
                    title,
                    flags=re.IGNORECASE,
                ).strip()
            if not title:
                title = title_from_slug(absolute)
            if not is_target_job(title) and not is_target_job(raw):
                continue
            if not is_target_job(title):
                title = raw.split(" iOS ")[0].strip() or title
            location = _luxoft_location(anchor)
            if not location:
                location = _luxoft_location_from_detail(absolute)
            jobs.append(
                {
                    "company": company,
                    "title": title,
                    "url": absolute,
                    "source": "company",
                    "location": location,
                }
            )
        return _partial_result(_ok(company, list_url, jobs, started, scanned=len(seen)), query_errors)
    except Exception as error:  # noqa: BLE001
        return _fail(company, list_url, error, started)


def collect_mind_studios() -> SourceResult:
    company = "Mind Studios"
    started = time.perf_counter()
    url = "https://themindstudios.com/api/v1/vacancies/"
    try:
        payload = fetch_json(url)
        if isinstance(payload, dict):
            items = payload.get("data") or payload.get("results") or payload.get("vacancies") or []
        else:
            items = payload
        if not isinstance(items, list):
            items = []
        jobs: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("name") or "").strip()
            if not is_target_job(title):
                continue
            slug = str(item.get("slug") or item.get("url") or "").strip()
            job_url = absolute_url(slug, "https://themindstudios.com/careers/") if slug else ""
            if not job_url:
                continue
            jobs.append(
                {
                    "company": company,
                    "title": title,
                    "url": job_url,
                    "source": "company",
                    "source_job_id": str(item.get("id")) if item.get("id") else None,
                    "location": item.get("location"),
                }
            )
        return _ok(
            company,
            url,
            jobs,
            started,
            scanned=len(items),
            empty_is_healthy=True,
        )
    except Exception as error:  # noqa: BLE001
        return _fail(company, url, error, started)


def collect_mwdn() -> SourceResult:
    company = "MWDN"
    started = time.perf_counter()
    list_url = "https://jobs.mwdn.com/careers/"
    try:
        from bs4 import BeautifulSoup

        html = fetch_text(list_url)
        document = BeautifulSoup(html, "lxml")
        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for anchor in document.select("a.comeet-position"):
            href = anchor.get("href") or ""
            absolute = absolute_url(href, "https://jobs.mwdn.com/")
            parts = [part for part in absolute.rstrip("/").split("/") if part]
            dedupe = parts[-2] if len(parts) >= 2 else absolute
            if dedupe in seen:
                continue
            seen.add(dedupe)
            name = anchor.select_one(".comeet-position-name")
            title = name.get_text(strip=True) if name else title_from_slug(absolute)
            if not is_target_job(title):
                continue
            jobs.append({"company": company, "title": title, "url": absolute, "source": "company"})
        return _ok(company, list_url, jobs, started, scanned=len(seen))
    except Exception as error:  # noqa: BLE001
        return _fail(company, list_url, error, started)


def collect_zone3000() -> SourceResult:
    company = "ZONE3000"
    started = time.perf_counter()
    try:
        payload = json.loads(_fetch_zone3000_api_text())
        items = payload if isinstance(payload, list) else []
        jobs: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not is_target_job(title):
                continue
            slug = str(item.get("url") or "").strip().lstrip("/")
            if not slug:
                continue
            job_url = f"{_ZONE3000_LIST_URL.rstrip('/')}/{slug}"
            location = "Remote" if item.get("remote") else None
            jobs.append(
                {
                    "company": company,
                    "title": title,
                    "url": job_url,
                    "source": "company",
                    "source_job_id": str(item.get("id")) if item.get("id") is not None else None,
                    "location": location,
                }
            )
        return _ok(company, _ZONE3000_API_URL, jobs, started, scanned=len(items))
    except Exception as error:  # noqa: BLE001
        return _fail(company, _ZONE3000_API_URL, error, started)


@contextmanager
def _secondary_query(errors: list[str], keyword: str):
    try:
        yield
    except Exception as error:  # noqa: BLE001
        errors.append(f"{keyword}: {error}")


def _partial_result(result: SourceResult, errors: list[str]) -> SourceResult:
    if errors:
        result.status = "degraded"
        result.error = "Secondary search incomplete: " + "; ".join(errors)
    return result
