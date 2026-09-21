#!/usr/bin/env python3
"""Register DOU companies whose careers page shows iOS or mobile hiring.

Company size is not a criterion. A company is added only when its careers page
(or its current DOU vacancy titles) names iOS or a mobile stack and the
watchlist collector can parse that page. Additions go to
database/company_discovered.json, which the watchlist refresh merges, and
straight into the watchlist. Sites that refuse automated clients are skipped,
never worked around; the DOU RSS feed still covers their DOU postings.

The run is incremental: database/company_discovery_state.json records when
each catalog company was last inspected (slug and date, no findings). New
catalog companies are inspected first, then at most --recheck companies whose
last check is older than --recheck-days. Requests to DOU are paced, because an
unpaced sweep of the whole catalog gets the client blocked by DOU, and the
production collector reads DOU's RSS feed from the same kind of host.
Output is counts only: which company matched is a search result.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.company_watchlist import collect_watchlist_company, default_watchlist_path  # noqa: E402
from collector.dou_catalog import USER_AGENT, discover_companies  # noqa: E402
from collector.dou_service_ratings import default_discovered_path, load_manual_additions  # noqa: E402
from collector.mobile_discovery import inspect_company, strength  # noqa: E402
from collector.types import STATUS_FAILED  # noqa: E402

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126 Safari/537.36"
)
_TIMEOUT = 20
# About 2,400 DOU requests an hour; ~30,000 unpaced requests in an hour got a client blocked.
_DOU_INTERVAL_SECONDS = 1.5
_local = threading.local()


class _DouPace:
    """Serialises requests to DOU hosts at a fixed minimum interval across threads."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self, url: str) -> None:
        host = (urlparse(url).hostname or "").lower()
        if not (host == "dou.ua" or host.endswith(".dou.ua")):
            return
        with self.lock:
            now = time.monotonic()
            if now < self.next_at:
                time.sleep(self.next_at - now)
            self.next_at = max(now, self.next_at) + self.interval


_PACE = _DouPace(_DOU_INTERVAL_SECONDS)


class _PacedSession(requests.Session):
    def request(self, method, url, *args, **kwargs):  # type: ignore[override]
        _PACE.wait(str(url))
        return super().request(method, url, *args, **kwargs)


def _fetch(url: str) -> tuple[int, str]:
    session = getattr(_local, "session", None)
    if session is None:
        session = _PacedSession()
        session.headers.update({"User-Agent": _BROWSER_UA, "Accept-Language": "en,uk;q=0.8"})
        _local.session = session
    try:
        response = session.get(url, timeout=_TIMEOUT)
    except requests.RequestException:
        return -1, ""
    return response.status_code, response.text if response.status_code == 200 else ""


def default_state_path(root: Path = ROOT) -> Path:
    return root / "database" / "company_discovery_state.json"


def load_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(slug): str(day) for slug, day in payload.items()} if isinstance(payload, dict) else {}


def select_companies(
    catalog: list[dict[str, Any]],
    *,
    known: set[str],
    state: dict[str, str],
    today: date,
    recheck_days: int,
    recheck_limit: int,
) -> list[dict[str, Any]]:
    """New catalog companies first, then the oldest checks past the re-check age."""
    fresh = [company for company in catalog if company["slug"] not in known and company["slug"] not in state]
    cutoff = (today - timedelta(days=recheck_days)).isoformat()
    stale = sorted(
        (company for company in catalog
         if company["slug"] not in known and company["slug"] in state and state[company["slug"]] < cutoff),
        key=lambda company: state[company["slug"]],
    )
    return fresh + stale[:recheck_limit]


def _evaluate(company: dict[str, Any]) -> dict[str, Any] | None:
    slug = str(company["slug"])
    row = inspect_company(slug, _fetch, has_dou_vacancies=int(company.get("vacancy_count") or 0) > 0)
    if strength(row) is None:
        return None
    entry = {"name": str(company.get("name") or slug), "slug": slug, "career_url": row["career_url"]}
    result = collect_watchlist_company(entry)
    # A page the collector cannot read would sit in the digest as degraded forever.
    if result.status == STATUS_FAILED or result.items_scanned <= 0:
        return None
    return entry


def watchlist_entry(entry: dict[str, str]) -> dict[str, Any]:
    return {
        "name": entry["name"],
        "slug": entry["slug"],
        "rating_score": None,
        "compensation_score": None,
        "survey_count": None,
        "dou_company_url": f"https://jobs.dou.ua/companies/{entry['slug']}/",
        "company_site_url": None,
        "career_url": entry["career_url"],
        "career_url_source": "discovery",
        "enabled": True,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Report counts without writing files.")
    parser.add_argument("--recheck", type=int, default=300, help="Re-check at most this many stale companies.")
    parser.add_argument("--recheck-days", type=int, default=90)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    watchlist_path = default_watchlist_path(ROOT)
    discovered_path = default_discovered_path(ROOT)
    state_path = default_state_path()
    watchlist = json.loads(watchlist_path.read_text(encoding="utf-8"))
    discovered = load_manual_additions(discovered_path)
    state = load_state(state_path)
    known = {str(company.get("slug")) for company in watchlist["companies"]}
    known |= {str(company.get("slug")) for company in discovered}

    session = _PacedSession()
    session.headers.update({"User-Agent": USER_AGENT})
    catalog = discover_companies(session)
    today = date.today()
    todo = select_companies(
        catalog, known=known, state=state, today=today,
        recheck_days=args.recheck_days, recheck_limit=args.recheck,
    )

    added: list[dict[str, str]] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_evaluate, company): company["slug"] for company in todo}
        for future in as_completed(futures):
            try:
                entry = future.result()
            except Exception:  # noqa: BLE001
                failures += 1
                continue
            state[futures[future]] = today.isoformat()
            if entry:
                added.append(entry)

    print(f"Catalog companies: {len(catalog)}; inspected: {len(todo)}; added: {len(added)}; errors: {failures}")
    if args.dry_run:
        return 0

    _write_json(state_path, dict(sorted(state.items())))
    if added:
        added.sort(key=lambda entry: entry["slug"])
        _write_json(discovered_path, sorted(discovered + added, key=lambda company: str(company.get("slug"))))
        watchlist["companies"].extend(watchlist_entry(entry) for entry in added)
        _write_json(watchlist_path, watchlist)
    print(f"Wrote {state_path.relative_to(ROOT)}" + (f", {discovered_path.relative_to(ROOT)} and "
          f"{watchlist_path.relative_to(ROOT)}" if added else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
