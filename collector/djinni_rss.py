"""Collect vacancies from the public Djinni iOS RSS feed.

The feed path is not disallowed by djinni.co/robots.txt. Items carry no
employer name, so the company stays empty rather than guessed.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from typing import Any

from collector.dou_rss import _published_at, strip_tracking
from collector.results import source_failed, source_ok
from collector.types import SourceResult
from integrations.http_client import fetch_text
from parser.normalize import is_target_job

FEED_URL = "https://djinni.co/jobs/rss/?primary_keyword=iOS"
SOURCE_ID = "djinni-ios-rss"
SOURCE_NAME = "Djinni iOS"

_JOB_ID = re.compile(r"/jobs/(\d+)")


def _job_from_item(item: ET.Element) -> dict[str, Any] | None:
    title = re.sub(r"\s+", " ", item.findtext("title") or "").strip()
    link = (item.findtext("link") or "").strip()
    if not title or not link:
        return None
    url = strip_tracking(link)
    job_id = _JOB_ID.search(url)
    return {
        "company": "",
        "title": title,
        "url": url,
        "source": "djinni",
        "source_job_id": f"djinni:{job_id.group(1)}" if job_id else None,
        "location": None,
        "remote": "unknown",
        "description": (item.findtext("description") or "").strip() or None,
        "published_at": _published_at(item.findtext("pubDate")),
    }


def parse_feed(xml_text: str) -> tuple[list[dict[str, Any]], int]:
    """Return target jobs and the number of feed items read."""
    items = ET.fromstring(xml_text).findall("./channel/item")
    jobs: list[dict[str, Any]] = []
    for item in items:
        job = _job_from_item(item)
        if job is not None and is_target_job(job["title"], job["description"]):
            jobs.append(job)
    return jobs, len(items)


def collect_djinni_ios_rss() -> SourceResult:
    started = time.perf_counter()
    try:
        jobs, scanned = parse_feed(fetch_text(FEED_URL))
    except Exception as error:  # noqa: BLE001
        return source_failed(SOURCE_NAME, FEED_URL, error, started, source_id=SOURCE_ID)
    return source_ok(SOURCE_NAME, FEED_URL, jobs, started, scanned=scanned, source_id=SOURCE_ID)
