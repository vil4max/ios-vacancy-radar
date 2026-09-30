"""Public ATS job-board APIs used instead of scraping a company's career page.

Boards are listed per watchlist slug in `database/company_ats_boards.json` only
after the board was verified to belong to that company (scripts/discover_ats_boards.py).
"""
from __future__ import annotations

import html
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

from integrations.http_client import fetch_json
from parser.normalize import is_target_job

Job = dict[str, Any]


def default_ats_boards_path(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parents[1]
    return base / "database" / "company_ats_boards.json"


def load_ats_boards(path: Path | None = None) -> dict[str, dict[str, str]]:
    target = path or default_ats_boards_path()
    if not target.exists():
        return {}
    payload = json.loads(target.read_text(encoding="utf-8"))
    boards = payload.get("boards") if isinstance(payload, dict) else None
    if not isinstance(boards, dict):
        raise ValueError("ATS board map must contain a boards object")
    result: dict[str, dict[str, str]] = {}
    for slug, board in boards.items():
        if not isinstance(board, dict):
            continue
        ats, token = str(board.get("ats") or ""), str(board.get("token") or "")
        if ats not in _COLLECTORS or not token:
            # One unusable entry must not fail every watchlist company: this map
            # is loaded once for the whole run. The company falls back to its
            # career page, and the warning names the entry to fix. Discovery
            # (scripts/discover_ats_boards.py) can report an ATS that has no
            # collector here yet.
            print(f"Skipping unsupported ATS board for {slug}: {ats!r}", file=sys.stderr)
            continue
        result[str(slug)] = {"ats": ats, "token": token}
    return result


def _join(*parts: Any) -> str | None:
    text = "\n".join(str(part) for part in parts if part)
    return text or None


def _expect(payload: Any, key: str | None, ats: str) -> list[dict[str, Any]]:
    items = payload.get(key) if key and isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise RuntimeError(f"{ats} API returned an unexpected payload")
    return [item for item in items if isinstance(item, dict)]


def _greenhouse(token: str) -> list[dict[str, Any]]:
    payload = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{quote(token)}/jobs?content=true")
    return _expect(payload, "jobs", "Greenhouse")


def _greenhouse_job(item: dict[str, Any]) -> Job:
    location = item.get("location") if isinstance(item.get("location"), dict) else {}
    return {
        "title": str(item.get("title") or "").strip(),
        "url": str(item.get("absolute_url") or ""),
        "source_job_id": str(item.get("id") or ""),
        "location": str(location.get("name") or "").strip() or None,
        # Greenhouse returns HTML-escaped markup in `content`.
        "description": html.unescape(str(item.get("content") or "")) or None,
    }


def _lever(token: str) -> list[dict[str, Any]]:
    return _expect(fetch_json(f"https://api.lever.co/v0/postings/{quote(token)}?mode=json"), None, "Lever")


def _lever_job(item: dict[str, Any]) -> Job:
    categories = item.get("categories") if isinstance(item.get("categories"), dict) else {}
    lists = item.get("lists") if isinstance(item.get("lists"), list) else []
    job: Job = {
        "title": str(item.get("text") or "").strip(),
        "url": str(item.get("hostedUrl") or ""),
        "source_job_id": str(item.get("id") or ""),
        "location": str(categories.get("location") or "").strip() or None,
        "description": _join(
            item.get("descriptionPlain"),
            *(f"{entry.get('text') or ''}\n{entry.get('content') or ''}" for entry in lists if isinstance(entry, dict)),
            item.get("additionalPlain"),
        ),
    }
    if item.get("workplaceType") == "remote":
        job["remote"] = "remote"
    return job


def _ashby(token: str) -> list[dict[str, Any]]:
    payload = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{quote(token)}")
    return [item for item in _expect(payload, "jobs", "Ashby") if item.get("isListed") is not False]


def _ashby_job(item: dict[str, Any]) -> Job:
    secondary = item.get("secondaryLocations") if isinstance(item.get("secondaryLocations"), list) else []
    locations = [str(item.get("location") or "").strip()] + [
        str(entry.get("location") or "").strip() for entry in secondary if isinstance(entry, dict)
    ]
    job: Job = {
        "title": str(item.get("title") or "").strip(),
        "url": str(item.get("jobUrl") or ""),
        "source_job_id": str(item.get("id") or ""),
        "location": " / ".join(dict.fromkeys(label for label in locations if label)) or None,
        "description": str(item.get("descriptionPlain") or "") or None,
    }
    if item.get("workplaceType") == "Remote":
        job["remote"] = "remote"
    return job


def _breezy(token: str) -> list[dict[str, Any]]:
    return _expect(fetch_json(f"https://{quote(token)}.breezy.hr/json"), None, "Breezy")


def _breezy_job(item: dict[str, Any]) -> Job:
    locations = item.get("locations") if isinstance(item.get("locations"), list) else [item.get("location")]
    labels = []
    remote = False
    for location in locations:
        if not isinstance(location, dict):
            continue
        remote = remote or bool(location.get("is_remote"))
        country = location.get("country") if isinstance(location.get("country"), dict) else {}
        label = ", ".join(part for part in (str(location.get("city") or ""), str(country.get("name") or "")) if part)
        if label:
            labels.append(label)
    job: Job = {
        "title": str(item.get("name") or "").strip(),
        "url": str(item.get("url") or ""),
        "source_job_id": str(item.get("id") or ""),
        "location": " / ".join(dict.fromkeys(labels)) or None,
    }
    if remote:
        job["remote"] = "remote"
    return job


def _recruitee(token: str) -> list[dict[str, Any]]:
    payload = fetch_json(f"https://{quote(token)}.recruitee.com/api/offers/")
    return [item for item in _expect(payload, "offers", "Recruitee") if item.get("status", "published") == "published"]


def _recruitee_job(item: dict[str, Any]) -> Job:
    job: Job = {
        "title": str(item.get("title") or "").strip(),
        "url": str(item.get("careers_url") or ""),
        "source_job_id": str(item.get("id") or ""),
        "location": str(item.get("location") or "").strip() or None,
        "description": _join(item.get("description"), item.get("requirements")),
    }
    if item.get("remote") is True:
        job["remote"] = "remote"
    return job


def _workable(token: str) -> list[dict[str, Any]]:
    """Public account widget; it carries titles and locations but no description."""
    payload = fetch_json(f"https://apply.workable.com/api/v1/widget/accounts/{quote(token)}")
    if not isinstance(payload, dict):
        raise RuntimeError("Workable API returned an unexpected payload")
    if not isinstance(payload.get("jobs"), list):
        raise RuntimeError("Workable API payload is missing jobs")
    return _expect(payload, "jobs", "Workable")


def _workable_job(item: dict[str, Any]) -> Job:
    locations = item.get("locations") if isinstance(item.get("locations"), list) else []
    labels = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        label = ", ".join(
            part
            for part in (str(location.get("city") or "").strip(), str(location.get("country") or "").strip())
            if part
        )
        if label:
            labels.append(label)
    job: Job = {
        "title": str(item.get("title") or "").strip(),
        "url": str(item.get("url") or item.get("shortlink") or ""),
        "source_job_id": str(item.get("shortcode") or ""),
        "location": " / ".join(dict.fromkeys(labels)) or None,
    }
    if item.get("telecommuting"):
        job["remote"] = "remote"
    return job


_COLLECTORS: dict[str, tuple[Callable[[str], list[dict[str, Any]]], Callable[[dict[str, Any]], Job]]] = {
    "greenhouse": (_greenhouse, _greenhouse_job),
    "lever": (_lever, _lever_job),
    "ashby": (_ashby, _ashby_job),
    "breezy": (_breezy, _breezy_job),
    "recruitee": (_recruitee, _recruitee_job),
    "workable": (_workable, _workable_job),
}

SUPPORTED_ATS = frozenset(_COLLECTORS)


def collect_ats_board(company: str, board: dict[str, str]) -> tuple[list[Job], int]:
    fetch, to_job = _COLLECTORS[board["ats"]]
    items = fetch(board["token"])
    jobs: list[Job] = []
    for item in items:
        job = to_job(item)
        if not job["title"] or not job["url"].startswith("https://"):
            continue
        if not is_target_job(job["title"], job.get("description")):
            continue
        jobs.append({"company": company, "source": "company", **{k: v for k, v in job.items() if v is not None}})
    return jobs, len(items)
