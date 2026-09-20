from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from parser.normalize import Vacancy, normalize_token, role_family_key


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_seen_path(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parents[1]
    return base / "database" / "seen.json"


def seen_key(vacancy: Vacancy) -> str:
    if vacancy.canonical_url:
        return vacancy.canonical_url
    return vacancy.identity_key or vacancy.hash


def seen_roles(seen: dict[str, dict[str, Any]]) -> set[tuple[str, str]]:
    return {
        role_family_key(str(meta["company"]), str(meta["title"]))
        for meta in seen.values()
        if meta.get("company") and meta.get("title")
    }


# The store lists public vacancies only. Application decisions (applied,
# dropped, archived) live in the private CRM board.
PRIVATE_SEEN_FIELDS = ("disposition", "applied_at")


def sanitize_seen(data: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(data, dict):
        return {}
    return {
        str(key): {field: value for field, value in record.items() if field not in PRIVATE_SEEN_FIELDS}
        for key, record in data.items()
        if isinstance(record, dict)
    }


def load_seen(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    return sanitize_seen(json.loads(path.read_text(encoding="utf-8")))


def save_seen(path: Path, seen: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = dict(sorted(sanitize_seen(seen).items(), key=lambda item: item[0]))
    path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def mark_seen(
    seen: dict[str, dict[str, Any]],
    vacancy: Vacancy,
    *,
    first_seen: str | None = None,
) -> bool:
    key = seen_key(vacancy)
    if not key or key in seen:
        return False
    seen[key] = {
        "title": vacancy.title,
        "company": vacancy.company,
        "first_seen": first_seen or utc_now(),
    }
    return True


def purge_dead_seen(
    seen: dict[str, dict[str, Any]],
    *,
    live_urls: set[str],
    purgeable_companies: set[str] | frozenset[str],
    confirmed_closed_urls: set[str] | frozenset[str] = frozenset(),
) -> list[str]:
    # A partial listing is not evidence of closure.
    if not purgeable_companies or not confirmed_closed_urls:
        return []
    purgeable = {normalize_token(name) for name in purgeable_companies if name.strip()}
    if not purgeable:
        return []
    removed: list[str] = []
    for key, meta in list(seen.items()):
        if key not in confirmed_closed_urls:
            continue
        company = normalize_token(str(meta.get("company") or ""))
        if not company or company not in purgeable:
            continue
        if key in live_urls:
            continue
        del seen[key]
        removed.append(key)
    return removed
