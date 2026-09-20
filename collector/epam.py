from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from collector.results import source_failed, source_ok
from collector.types import SourceResult
from integrations.http_client import fetch_text
from parser.normalize import is_target_job

_COMPANY = "EPAM"
_SOURCE_ID = "company:epam@careers.epam.com"
_SITEMAP_URL = "https://careers.epam.com/sitemap.xml.gz"
_SOURCE_URL = "https://careers.epam.com/en/jobs?search=iOS&specialization=developer"
_VACANCY_LOC = re.compile(
    r"<loc>(https://careers\.epam\.com/en/vacancy/[^<]+)</loc>",
    re.IGNORECASE,
)
_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)
_IOS_SLUG = re.compile(r"(?i)(ios|swift)")
_MAX_WORKERS = 4


def _titled_names(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("name")
        if title:
            names.append(str(title).strip())
    return [name for name in names if name]


def _format_location(cities: list[str], countries: list[str]) -> str | None:
    if cities and countries:
        if len(cities) == 1 and len(countries) == 1:
            return f"{cities[0]}, {countries[0]}"
        return " / ".join(cities + countries)
    if countries:
        return " / ".join(countries)
    if cities:
        return " / ".join(cities)
    return None


def _map_remote(vacancy_types: list[str]) -> str:
    text = " ".join(vacancy_types).lower()
    if "remote" in text:
        return "remote"
    if "hybrid" in text:
        return "hybrid"
    if "office" in text or "onsite" in text or "on-site" in text:
        return "onsite"
    return "unknown"


def discover_ios_vacancy_urls(sitemap_xml: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in _VACANCY_LOC.finditer(sitemap_xml):
        url = match.group(1)
        if not _IOS_SLUG.search(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def parse_vacancy_page(html: str, url: str) -> dict[str, Any] | None:
    match = _NEXT_DATA.search(html)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None

    job = (
        payload.get("props", {})
        .get("pageProps", {})
        .get("job")
    )
    if not isinstance(job, dict):
        return None
    if job.get("is_expired") is True:
        return None

    title = str(job.get("name") or "").strip()
    if not title:
        return None

    # The summary omits requirements; prefer the complete vacancy body.
    description = next(
        (str(value).strip() for value in (job.get("text"), job.get("description"))
         if value is not None and str(value).strip()),
        None,
    )

    if not is_target_job(title, description):
        return None

    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    countries = _titled_names(metadata.get("country") or job.get("country"))
    cities = _titled_names(metadata.get("city") or job.get("city"))
    vacancy_types = _titled_names(metadata.get("vacancy_type") or job.get("vacancy_type"))

    location = _format_location(cities, countries)
    source_job_id = job.get("uid") or job.get("unique_id")
    return {
        "company": _COMPANY,
        "title": title,
        "url": url,
        "source": "company",
        "source_job_id": str(source_job_id).strip() if source_job_id else None,
        "description": description,
        "location": location,
        "remote": _map_remote(vacancy_types),
    }


def _fetch_vacancy(url: str) -> dict[str, Any] | None:
    html = fetch_text(url)
    return parse_vacancy_page(html, url)


def collect_epam() -> SourceResult:
    started = time.perf_counter()
    try:
        sitemap = fetch_text(_SITEMAP_URL)
        candidates = discover_ios_vacancy_urls(sitemap)
        if not candidates:
            return source_ok(_COMPANY, _SOURCE_URL, [], started, scanned=0, source_id=_SOURCE_ID)

        jobs: list[dict[str, Any]] = []
        errors = 0
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {pool.submit(_fetch_vacancy, url): url for url in candidates}
            for future in as_completed(futures):
                try:
                    job = future.result()
                    if job is not None:
                        jobs.append(job)
                except Exception:  # noqa: BLE001
                    errors += 1

        if errors == len(candidates):
            return source_failed(
                _COMPANY,
                _SOURCE_URL,
                f"all {errors} vacancy detail fetches failed",
                started,
                source_id=_SOURCE_ID,
            )

        return source_ok(
            _COMPANY,
            _SOURCE_URL,
            jobs,
            started,
            scanned=len(candidates) - errors,
            source_id=_SOURCE_ID,
        )
    except Exception as error:  # noqa: BLE001
        return source_failed(_COMPANY, _SOURCE_URL, error, started, source_id=_SOURCE_ID)
