"""Collect public iOS vacancies from the findmyremote.ai listing page.

The source reads one fixed page, once per run: the first page of the public
engineering/iOS listing. It never calls the site's /api/, /app/ or /auth/
paths, never pages through "Load more", and identifies itself with an honest
user agent. The shared client's fallback that impersonates a browser is not
used: a refused request is reported, not worked around.
"""
from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

from collector.results import source_failed, source_ok
from collector.types import STATUS_DEGRADED, SourceResult
from integrations.http_client import fetch_text_allowing_bot_wall
from parser.normalize import is_target_job

SITE_HOST = "findmyremote.ai"
SITE_URL = f"https://{SITE_HOST}"
LISTING_URL = f"{SITE_URL}/jobs?category=engineering&skill=ios"
SOURCE_NAME = "Find My Remote (iOS listing)"
SOURCE_ID = "findmyremote:ios-listing"
USER_AGENT = "ios-vacancy-radar/1.0 (+https://github.com/vil4max/ios-vacancy-radar)"
_TIMEOUT_SECONDS = 20

# The site's job cards link to /companies/<company>/jobs/<job>; the company
# link of a card points to /companies/<company>.
_JOB_PATH = re.compile(r"^/companies/[^/?#]+/jobs/[^/?#]+/?$")
_COMPANY_PATH = re.compile(r"^/companies/[^/?#]+/?$")


def _text(node: Tag) -> str:
    return " ".join(node.get_text(" ", strip=True).split())


def _is_site_link(href: str) -> bool:
    host = (urlsplit(href).hostname or "").lower()
    return host == SITE_HOST or host.endswith(f".{SITE_HOST}")


def _employer_url(card: Tag) -> str | None:
    """The employer's own posting link, when the card carries one."""
    for anchor in card.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if urlsplit(href).scheme in {"http", "https"} and not _is_site_link(href):
            return href
    return None


def _location(card: Tag) -> str | None:
    """Allowed countries, or "Remote", from the paragraph next to the pin icon."""
    icon = card.find("svg", class_="tabler-icon-map-pin")
    paragraph = icon.find_next_sibling("p") if icon else None
    return (_text(paragraph) or None) if paragraph else None


def _job_from_card(title_link: Tag) -> dict[str, Any] | None:
    card = title_link.find_parent(attrs={"data-slot": "card"})
    company_link = card.find("a", href=_COMPANY_PATH) if card else None
    title = _text(title_link)
    company = _text(company_link) if company_link else ""
    if card is None or not title or not company:
        return None
    job_page = urljoin(f"{SITE_URL}/", str(title_link["href"]).strip())
    return {
        "company": company,
        "title": title,
        "url": _employer_url(card) or job_page,
        "source": SITE_HOST,
        "location": _location(card),
        # The board lists remote positions only; the card's countries say
        # where the person may live, which the labels read as a location.
        "remote": "remote",
    }


def parse_listing(html: str) -> tuple[list[dict[str, Any]], int, int]:
    """Return (records, cards found, cards skipped).

    A record is built for every readable card, whatever its title: the topic
    filter is the caller's step, so the scanned count stays the page's own.
    """
    document = BeautifulSoup(html, "lxml")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    skipped = 0
    for title_link in document.find_all("a", href=_JOB_PATH):
        href = str(title_link["href"]).strip()
        if href in seen:
            continue
        seen.add(href)
        record = _job_from_card(title_link)
        if record is None:
            skipped += 1
        else:
            records.append(record)
    return records, len(seen), skipped


def _fetch_listing() -> str:
    html = fetch_text_allowing_bot_wall(
        LISTING_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        timeout=_TIMEOUT_SECONDS,
    )
    if html is None:
        # Matches the access-blocked wording the pipeline routes to manual review.
        raise RuntimeError(f"HTTP 403 or anti-bot challenge for {LISTING_URL}; no workaround is attempted")
    if not html.strip():
        raise RuntimeError(f"empty response for {LISTING_URL}")
    return html


def _structure_error(records: list[dict[str, Any]], found: int) -> str | None:
    if found == 0:
        return "no job cards found; the page structure no longer matches the parser"
    if not records:
        return f"{found} job cards found but none readable; the page structure no longer matches the parser"
    if not any(record["location"] for record in records):
        return "no job card carries allowed-country text; the page structure no longer matches the parser"
    return None


def collect_findmyremote() -> SourceResult:
    started = time.perf_counter()
    try:
        records, found, skipped = parse_listing(_fetch_listing())
    except Exception as error:  # noqa: BLE001
        return source_failed(SOURCE_NAME, LISTING_URL, error, started, source_id=SOURCE_ID)
    jobs = [record for record in records if is_target_job(record["title"])]
    result = source_ok(SOURCE_NAME, LISTING_URL, jobs, started, scanned=len(records), source_id=SOURCE_ID)
    result.items_skipped = skipped
    problem = _structure_error(records, found)
    if problem:
        result.status = STATUS_DEGRADED
        result.error = problem
    return result
