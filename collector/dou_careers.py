from __future__ import annotations

import html
import re
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from parser.normalize import is_ios_job

COMPANY_SITE_PATTERN = re.compile(
    r'<div class="site">\s*<a href="([^"]+)" target="_blank" rel="nofollow">',
    re.IGNORECASE | re.DOTALL,
)
GENERIC_VACANCY_PATTERN = re.compile(
    r'<a[^>]+href="([^"]+)"[^>]*>\s*([^<]+)\s*</a>',
    re.IGNORECASE | re.DOTALL,
)


def extract_company_site_url(profile_html: str) -> str | None:
    match = COMPANY_SITE_PATTERN.search(profile_html)
    if not match:
        return None
    return html.unescape(match.group(1).strip())


def _normalize_fetch_url(url: str) -> str:
    cleaned = html.unescape(url.strip())
    return cleaned.replace("&amp;", "&")


def _job_dict(company: str, title: str, url: str, source_job_id: str | None = None) -> dict[str, Any]:
    return {
        "company": company,
        "title": title.strip(),
        "url": url,
        "source": "company",
        "source_job_id": source_job_id,
    }


def _scrape_generic_careers(company: str, site_url: str, page_html: str) -> list[dict[str, Any]]:
    base_url = _normalize_fetch_url(site_url)
    jobs: list[dict[str, Any]] = []
    seen: set[str] = set()

    for match in GENERIC_VACANCY_PATTERN.finditer(page_html):
        href = unescape(match.group(1).strip())
        title = unescape(match.group(2).strip())
        if not title:
            continue
        if not is_ios_job(title) and not is_ios_job(href):
            continue

        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if not parsed.scheme.startswith("http"):
            continue
        lowered = absolute.lower()
        if not any(token in lowered for token in ("vacanc", "job", "career", "position", "opening")):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        jobs.append(_job_dict(company, title, absolute))

    return jobs


def collect_jobs_from_career_site(
    company: str,
    site_url: str,
    session: requests.Session,
) -> list[dict[str, Any]]:
    normalized_url = _normalize_fetch_url(site_url)
    jobs_by_url: dict[str, dict[str, Any]] = {}

    try:
        response = session.get(normalized_url, timeout=30)
        if response.status_code != 200:
            return []
        page_html = response.text
    except requests.RequestException:
        return []

    for job in _scrape_generic_careers(company, normalized_url, page_html):
        jobs_by_url[job["url"]] = job

    return list(jobs_by_url.values())

