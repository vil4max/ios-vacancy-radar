"""Collect public iOS vacancies from the Hirify search API."""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode

from collector.results import source_failed, source_ok
from collector.types import SourceResult
from integrations.http_client import fetch_json
from parser.normalize import is_target_job

API_URL = "https://api.hirify.me/api/vacancies"
SOURCE_NAME = "Hirify (saved search)"
SOURCE_ID = "hirify:saved-search"
_UNKNOWN_COMPANY = "%hirify_global%"  # confidential posting; company not disclosed yet
SEARCH_PARAMS: dict[str, str] = {
    "specializations": "ios_dev",
    "skills": "swift",
    "grade": "middle,senior,lead",
    "excluded_grade": "trainee,junior",
    "excluded_skills": "android,flutter,react native,kotlin",
    "excluded_english_level": "c2,c1",
    "work_format": "remote,hybrid,onsite",
    "remote_type": "global",
}
# Bound pagination for the public search endpoint.
_PAGE_LIMIT = 10


def _location(item: dict[str, Any]) -> str | None:
    offices = item.get("office_locations") or []
    labels = [str(office).replace("_", " ").title() for office in offices if office]
    return " / ".join(dict.fromkeys(labels)) or None


def _remote(item: dict[str, Any]) -> str:
    formats = item.get("work_format") or []
    for mode in ("remote", "hybrid", "onsite"):
        if mode in formats:
            return mode
    return "unknown"


def _description(item: dict[str, Any]) -> str | None:
    parts = [str(item.get("tldr") or "")]
    tags = [str(tag.get("name") or "") for tag in item.get("tags") or [] if isinstance(tag, dict)]
    if tags:
        parts.append("Stack: " + ", ".join(tags))
    text = "\n".join(part for part in parts if part)
    return text or None


def _job_from_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if item.get("is_archived") or item.get("is_scam") or item.get("is_potential_scam"):
        return None
    title = str(item.get("title") or item.get("original_title") or "").strip()
    slug = str(item.get("slug") or "").strip()
    job_id = item.get("id")
    if not title or not slug or not job_id:
        return None
    description = _description(item)
    if not is_target_job(title, description):
        return None
    company = str(item.get("company_title") or "").strip()
    if not company or company == _UNKNOWN_COMPANY:
        company = "Hirify"
    return {
        "company": company,
        "title": title,
        "url": f"https://hirify.me/jobs/{slug}",
        # Matches the id format the @hirifyme_bot Telegram path already uses,
        # so the same posting reaching the pipeline via both sources can dedupe.
        "source": "hirify.me",
        "source_job_id": f"hirify:{job_id}",
        "location": _location(item),
        "remote": _remote(item),
        "description": description,
        # "ru" is Hirify's "list of Russian tech companies" board; "ru-global"
        # (companies with Eastern-European roots) is deliberately not marked.
        "russian_company": item.get("source_secondary") == "ru",
    }


def collect_hirify() -> SourceResult:
    started = time.perf_counter()
    jobs: list[dict[str, Any]] = []
    scanned = 0
    try:
        for page in range(1, _PAGE_LIMIT + 1):
            query = urlencode({**SEARCH_PARAMS, "page": page})
            payload = fetch_json(f"{API_URL}?{query}", headers={"Accept": "application/json"})
            if not isinstance(payload, dict):
                raise RuntimeError("Hirify API returned an unexpected payload")
            items = payload.get("data")
            if not isinstance(items, list):
                raise RuntimeError("Hirify API payload is missing data")
            scanned += len(items)
            for item in items:
                if not isinstance(item, dict):
                    continue
                job = _job_from_item(item)
                if job:
                    jobs.append(job)
            if page >= int(payload.get("last_page") or 1):
                break
    except Exception as error:  # noqa: BLE001
        return source_failed(SOURCE_NAME, "https://hirify.me/", error, started, source_id=SOURCE_ID)
    return source_ok(SOURCE_NAME, "https://hirify.me/", jobs, started, scanned=scanned, source_id=SOURCE_ID)
