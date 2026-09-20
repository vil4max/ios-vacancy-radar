"""Hand-over feed: the vacancies the collector gathered, for a consumer.

The feed is a search result, so it is written only to the private state store
and never inside this public repository. The collector appends and prunes; it
does not record what the consumer did with an entry. The consumer keeps its own
processing state on its side.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from parser.normalize import Vacancy, posting_language, role_family_key, vacancy_labels

SCHEMA_VERSION = 1
# The consumer reads the feed daily; a month covers long gaps without letting
# the file grow without bound.
RETENTION_DAYS = 30
# Enough for requirements and conditions; postings are public, but an unbounded
# HTML body would make every publish commit heavy.
DESCRIPTION_LIMIT = 6000


def _plain_text(description: str | None) -> str:
    return BeautifulSoup(description or "", "html.parser").get_text("\n", strip=True)


def feed_entry(vacancy: Vacancy, *, first_seen: str) -> dict[str, Any]:
    text = _plain_text(vacancy.description)
    return {
        "company": vacancy.company,
        "title": vacancy.title,
        "url": vacancy.url,
        "source": vacancy.source,
        "location": vacancy.location,
        "advertised_locations": list(vacancy.advertised_locations),
        "published_at": vacancy.published_at.isoformat() if vacancy.published_at else None,
        "first_seen": first_seen,
        # One role reaches the feed from several sources; the consumer reads
        # one description per role_key instead of one per URL.
        "role_key": " | ".join(role_family_key(vacancy.company, vacancy.title)),
        "labels": vacancy_labels(vacancy),
        "language": posting_language(f"{vacancy.title} {text}"),
        "description": text[:DESCRIPTION_LIMIT],
        # A cut description may hide requirements near its end.
        "description_truncated": len(text) > DESCRIPTION_LIMIT,
    }


def load_feed(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "vacancies": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    vacancies = data.get("vacancies") if isinstance(data, dict) else None
    return {"schema_version": SCHEMA_VERSION, "vacancies": vacancies if isinstance(vacancies, dict) else {}}


def append_feed(feed: dict[str, Any], vacancies: list[Vacancy], *, first_seen: str) -> int:
    added = 0
    for vacancy in vacancies:
        key = vacancy.canonical_url or vacancy.identity_key
        if not key or key in feed["vacancies"]:
            continue
        feed["vacancies"][key] = feed_entry(vacancy, first_seen=first_seen)
        added += 1
    return added


def prune_feed(feed: dict[str, Any], *, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=RETENTION_DAYS)
    stale = []
    for key, entry in feed["vacancies"].items():
        try:
            seen_at = datetime.fromisoformat(str(entry.get("first_seen")))
        except ValueError:
            continue
        if seen_at < cutoff:
            stale.append(key)
    for key in stale:
        del feed["vacancies"][key]
    return len(stale)


def save_feed(path: Path, feed: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {"schema_version": SCHEMA_VERSION, "vacancies": dict(sorted(feed["vacancies"].items()))}
    path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
