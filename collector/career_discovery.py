from __future__ import annotations

from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

_ATS_HOSTS = (
    "ashbyhq.com",
    "bamboohr.com",
    "comeet.co",
    "greenhouse.io",
    "jobs.lever.co",
    "oraclecloud.com",
    "recruitee.com",
    "smartrecruiters.com",
    "teamtailor.com",
    "workable.com",
)
_CAREER_TOKENS = ("career", "careers", "job", "jobs", "vacanc", "open-position", "open_position")


def _candidate_score(url: str, text: str) -> int:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    lowered_url = url.lower()
    lowered_text = text.lower()
    score = 0
    if any(host == ats or host.endswith(f".{ats}") for ats in _ATS_HOSTS):
        score += 100
    if any(token in lowered_url for token in _CAREER_TOKENS):
        score += 50
    if any(token in lowered_text for token in _CAREER_TOKENS):
        score += 30
    if any(token in lowered_url for token in ("blog", "news", "article")):
        score -= 80
    return score


def discover_career_url(company_site_url: str, html: str) -> str | None:
    if _candidate_score(company_site_url, "") >= 50:
        return company_site_url

    document = BeautifulSoup(html, "lxml")
    candidates: list[tuple[int, str]] = []
    for anchor in document.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(company_site_url, href)
        if urlparse(absolute).scheme not in {"http", "https"}:
            continue
        score = _candidate_score(absolute, anchor.get_text(" ", strip=True))
        if score > 0:
            candidates.append((score, absolute))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
    return candidates[0][1]


def resolve_career_url(company_site_url: str, session: requests.Session) -> str | None:
    response = session.get(company_site_url, timeout=30)
    response.raise_for_status()
    return discover_career_url(company_site_url, response.text)
