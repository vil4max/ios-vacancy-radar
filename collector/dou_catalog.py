from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any

import requests

from collector.dou_careers import extract_company_site_url

COMPANIES_INDEX_URL = "https://jobs.dou.ua/companies/"
COMPANIES_XHR_URL = "https://jobs.dou.ua/companies/xhr-load/"
USER_AGENT = "ios-hunter/2.0 (+https://github.com/)"

_CN_A_PATTERN = re.compile(
    r'<a class="cn-a" href="https://jobs\.dou\.ua/companies/([a-z0-9-]+)/">([^<]+)</a>',
    re.IGNORECASE,
)
_COMPANY_CARD_PATTERN = re.compile(
    r'<a class="cn-a" href="https://jobs\.dou\.ua/companies/([a-z0-9-]+)/">([^<]+)</a>'
    r"([\s\S]*?)<div class=\"site\">([\s\S]*?)</div>",
    re.IGNORECASE,
)
_VACANCIES_COUNT_PATTERN = re.compile(
    r"/vacancies/[^\"]*\"><span>Вакансії</span>\s*(\d*)",
    re.IGNORECASE,
)
_CSRF_PATTERN = re.compile(r'window\.CSRF_TOKEN\s*=\s*"([^"]+)"')
_L_COMPANY_PATTERN = re.compile(r'li class="l-company"', re.IGNORECASE)

DEFAULT_SEED_FEED_LIMIT = 300


def default_seed_path(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parents[1]
    return base / "database" / "dou_companies.json"


def vacancies_url_for(slug: str) -> str:
    return f"https://jobs.dou.ua/companies/{slug}/vacancies/"


def profile_url_for(slug: str) -> str:
    return f"https://jobs.dou.ua/companies/{slug}/"


def parse_companies_index(html: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _COMPANY_CARD_PATTERN.finditer(html):
        slug = match.group(1).strip().lower()
        if slug in seen:
            continue
        seen.add(slug)
        name = unescape(match.group(2)).strip()
        site_html = match.group(4)
        vac_match = _VACANCIES_COUNT_PATTERN.search(site_html)
        vacancy_count = int(vac_match.group(1)) if vac_match and vac_match.group(1) else 0
        found.append(
            {
                "name": name,
                "slug": slug,
                "site_url": None,
                "vacancies_url": vacancies_url_for(slug),
                "vacancy_count": vacancy_count,
            }
        )
    if found:
        return found

    for match in _CN_A_PATTERN.finditer(html):
        slug = match.group(1).strip().lower()
        if slug in seen:
            continue
        seen.add(slug)
        found.append(
            {
                "name": unescape(match.group(2)).strip(),
                "slug": slug,
                "site_url": None,
                "vacancies_url": vacancies_url_for(slug),
                "vacancy_count": 0,
            }
        )
    return found


def extract_csrf_token(html: str) -> str | None:
    match = _CSRF_PATTERN.search(html)
    return match.group(1) if match else None


def initial_list_count(html: str) -> int:
    matches = _L_COMPANY_PATTERN.findall(html)
    if matches:
        return len(matches)
    return len(parse_companies_index(html))


def empty_seed() -> dict[str, Any]:
    return {
        "updated_at": None,
        "source": COMPANIES_INDEX_URL,
        "companies": [],
    }


def load_seed(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_seed()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_seed()
    if not isinstance(payload, dict):
        return empty_seed()
    companies = payload.get("companies")
    if not isinstance(companies, list):
        companies = []
    return {
        "updated_at": payload.get("updated_at"),
        "source": payload.get("source") or COMPANIES_INDEX_URL,
        "companies": [c for c in companies if isinstance(c, dict) and c.get("slug")],
    }


def save_seed(path: Path, seed: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def merge_seed(old: dict[str, Any], new_companies: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, int]]:
    by_slug: dict[str, dict[str, Any]] = {}
    for item in old.get("companies") or []:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or "").strip().lower()
        if not slug:
            continue
        by_slug[slug] = {
            "name": str(item.get("name") or slug),
            "slug": slug,
            "site_url": item.get("site_url") or None,
            "vacancies_url": item.get("vacancies_url") or vacancies_url_for(slug),
            "vacancy_count": item.get("vacancy_count"),
        }

    added = 0
    updated = 0
    unchanged = 0
    for item in new_companies:
        slug = str(item.get("slug") or "").strip().lower()
        if not slug:
            continue
        name = str(item.get("name") or slug).strip()
        site_url = item.get("site_url") or None
        vacancy_count = item.get("vacancy_count")
        vacancies_url = item.get("vacancies_url") or vacancies_url_for(slug)
        existing = by_slug.get(slug)
        if existing is None:
            by_slug[slug] = {
                "name": name,
                "slug": slug,
                "site_url": site_url,
                "vacancies_url": vacancies_url,
                "vacancy_count": vacancy_count if vacancy_count is not None else 0,
            }
            added += 1
            continue

        changed = False
        if name and name != existing.get("name"):
            existing["name"] = name
            changed = True
        if vacancy_count is not None and vacancy_count != existing.get("vacancy_count"):
            existing["vacancy_count"] = vacancy_count
            changed = True
        if site_url and not existing.get("site_url"):
            existing["site_url"] = site_url
            changed = True
        if not existing.get("vacancies_url"):
            existing["vacancies_url"] = vacancies_url
            changed = True
        if changed:
            updated += 1
        else:
            unchanged += 1

    companies = sorted(by_slug.values(), key=lambda row: str(row.get("name") or "").lower())
    seed = {
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": COMPANIES_INDEX_URL,
        "companies": companies,
    }
    return seed, {
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "total": len(companies),
    }


def enrich_site_url(slug: str, session: requests.Session) -> str | None:
    response = session.get(profile_url_for(slug), timeout=30)
    response.raise_for_status()
    return extract_company_site_url(response.text)


def discover_companies(
    session: requests.Session,
    *,
    max_pages: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    index = session.get(COMPANIES_INDEX_URL, timeout=30)
    index.raise_for_status()
    csrf = extract_csrf_token(index.text)
    if not csrf:
        raise RuntimeError("DOU companies page did not include CSRF token")

    companies = parse_companies_index(index.text)
    count = initial_list_count(index.text)
    pages_fetched = 1

    while True:
        if max_pages is not None and pages_fetched >= max_pages:
            break
        if limit is not None and len(companies) >= limit:
            break

        response = session.post(
            COMPANIES_XHR_URL,
            data={"count": count, "csrfmiddlewaretoken": csrf},
            headers={
                "Referer": COMPANIES_INDEX_URL,
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": csrf,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        html = str(payload.get("html") or "")
        batch = parse_companies_index(html)
        if not batch:
            break

        seen = {row["slug"] for row in companies}
        for row in batch:
            if row["slug"] not in seen:
                companies.append(row)
                seen.add(row["slug"])

        num = int(payload.get("num") or 0)
        count += num
        pages_fetched += 1
        if payload.get("last") or num == 0:
            break

    if limit is not None:
        return companies[:limit]
    return companies


def apply_site_enrichment(
    companies: list[dict[str, Any]],
    session: requests.Session,
    *,
    only_missing: bool = True,
) -> int:
    filled = 0
    for row in companies:
        if only_missing and row.get("site_url"):
            continue
        slug = str(row.get("slug") or "")
        if not slug:
            continue
        try:
            site = enrich_site_url(slug, session)
        except requests.RequestException:
            continue
        if site:
            row["site_url"] = site
            filled += 1
    return filled


def companies_for_collect(
    seed: dict[str, Any],
    *,
    skip_slugs: set[str] | None = None,
    min_vacancies: int = 1,
    feed_limit: int | None = DEFAULT_SEED_FEED_LIMIT,
) -> list[dict[str, Any]]:
    skip = {slug.lower() for slug in (skip_slugs or set())}
    ranked: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = []

    for item in seed.get("companies") or []:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or "").strip().lower()
        if not slug or slug in skip:
            continue
        name = str(item.get("name") or slug).strip()
        if "vacancy_count" not in item or item.get("vacancy_count") is None:
            manual.append({"name": name, "slug": slug})
            continue
        try:
            vacancy_count = int(item.get("vacancy_count") or 0)
        except (TypeError, ValueError):
            vacancy_count = 0
        if vacancy_count < min_vacancies:
            continue
        ranked.append({"name": name, "slug": slug, "vacancy_count": vacancy_count})

    ranked.sort(key=lambda row: (-int(row.get("vacancy_count") or 0), str(row.get("name") or "").lower()))
    selected = manual + ranked
    if feed_limit is not None:
        selected = selected[:feed_limit]
    return selected


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session
