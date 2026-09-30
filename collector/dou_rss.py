"""Collect vacancies from the public jobs.dou.ua RSS feeds.

The feeds list postings whose employer career site may refuse automated
clients, so they cover companies the direct collectors cannot read.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from collector.results import source_failed, source_ok
from collector.types import SourceResult
from integrations.http_client import fetch_text
from parser.normalize import is_target_job

IOS_FEED_URL = "https://jobs.dou.ua/vacancies/feeds/?category=iOS/macOS"
AI_FEED_URL = "https://jobs.dou.ua/vacancies/feeds/?search=AI"
IOS_SOURCE_ID = "dou-ios-rss"
AI_SOURCE_ID = "dou-ai-rss"
IOS_SOURCE_NAME = "DOU iOS/macOS"
AI_SOURCE_NAME = "DOU AI (mobile)"

# The AI search is broad; only roles close to Apple platforms are kept from it.
_AI_TITLE_FILTER = re.compile(r"(?i)(?<![a-z])(?:mobile|ios|swift|swiftui|apple|macos)(?![a-z])")
_VACANCY_ID = re.compile(r"/vacancies/(\d+)/?")
_COMPANY_SLUG = re.compile(r"/companies/([^/]+)/")
_REMOTE_SEGMENT = "віддалено"
# Salary segments are dropped while splitting the title; the collector does not
# extract or keep pay, and a salary is not a location.
_SALARY_SEGMENT = re.compile(r"(?i)^(?:від\s+|до\s+)?[$€£]|\d\s*(?:\$|€|грн|uah|usd|eur)\b")


def strip_tracking(url: str) -> str:
    split = urlsplit(url.strip())
    query = [(key, value) for key, value in parse_qsl(split.query, keep_blank_values=True)
             if not key.lower().startswith("utm_")]
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), ""))


def _split_top_level(text: str) -> list[str]:
    """Split on commas outside parentheses: a company name may hold a comma."""
    parts: list[str] = []
    depth = 0
    current = ""
    for char in text:
        if char in "([":
            depth += 1
        elif char in ")]" and depth:
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
            continue
        current += char
    parts.append(current)
    return [part.strip() for part in parts if part.strip()]


def parse_item_title(raw_title: str) -> tuple[str, str | None, str | None, bool]:
    """Split "<Role> в <Company>, <locations, salary, remote>".

    Returns role, company, location and whether the posting is remote. The last
    " в " is the separator: a Ukrainian role name can contain the preposition,
    while the trailing segments never do.
    """
    title = re.sub(r"\s+", " ", unescape(raw_title)).strip()
    role, separator, tail = title.rpartition(" в ")
    if not separator or not role.strip():
        return title, None, None, False
    segments = _split_top_level(tail)
    if not segments:
        return role.strip(), None, None, False
    company, rest = segments[0], segments[1:]
    remote = any(segment.lower() == _REMOTE_SEGMENT for segment in rest)
    places = [
        segment for segment in rest
        if segment.lower() != _REMOTE_SEGMENT and not _SALARY_SEGMENT.search(segment)
    ]
    return role.strip(), company, ", ".join(places) or None, remote


def _published_at(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).isoformat()
    except (TypeError, ValueError):
        return None


def _job_from_item(item: ET.Element) -> dict[str, Any] | None:
    raw_title = item.findtext("title") or ""
    link = (item.findtext("link") or "").strip()
    if not raw_title.strip() or not link:
        return None
    url = strip_tracking(link)
    title, company, location, remote = parse_item_title(raw_title)
    if not company:
        slug = _COMPANY_SLUG.search(url)
        company = slug.group(1) if slug else None
    if not company:
        return None
    description = (item.findtext("description") or "").strip() or None
    vacancy_id = _VACANCY_ID.search(url)
    return {
        "company": company,
        "title": title,
        "url": url,
        "source": "dou",
        "source_job_id": f"dou:{vacancy_id.group(1)}" if vacancy_id else None,
        "location": location,
        "remote": "remote" if remote else "unknown",
        "description": description,
        "published_at": _published_at(item.findtext("pubDate")),
    }


def parse_feed(
    xml_text: str,
    *,
    title_filter: Callable[[str], bool] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return target jobs and the number of feed items read."""
    root = ET.fromstring(xml_text)
    items = root.findall("./channel/item")
    jobs: list[dict[str, Any]] = []
    for item in items:
        job = _job_from_item(item)
        if job is None:
            continue
        if title_filter is not None and not title_filter(job["title"]):
            continue
        if not is_target_job(job["title"], job["description"]):
            continue
        jobs.append(job)
    return jobs, len(items)


def is_mobile_ai_title(title: str) -> bool:
    return _AI_TITLE_FILTER.search(title) is not None


def _collect(
    name: str,
    source_id: str,
    url: str,
    title_filter: Callable[[str], bool] | None,
) -> SourceResult:
    started = time.perf_counter()
    try:
        jobs, scanned = parse_feed(fetch_text(url), title_filter=title_filter)
    except Exception as error:  # noqa: BLE001
        return source_failed(name, url, error, started, source_id=source_id)
    return source_ok(name, url, jobs, started, scanned=scanned, source_id=source_id)


def collect_dou_ios_rss() -> SourceResult:
    return _collect(IOS_SOURCE_NAME, IOS_SOURCE_ID, IOS_FEED_URL, None)


def collect_dou_ai_rss() -> SourceResult:
    return _collect(AI_SOURCE_NAME, AI_SOURCE_ID, AI_FEED_URL, is_mobile_ai_title)
