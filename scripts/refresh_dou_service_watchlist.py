#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.dou_service_ratings import (
    default_service_ratings_path,
    enrich_official_urls,
    fetch_service_ratings,
    load_career_overrides,
    load_manual_additions,
    merge_manual_companies,
    merge_top50_companies,
    preserve_watchlist_state,
    save_service_ratings,
)
from collector.dou_top50 import fetch_top50
from config.paths import workspace_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the research-only watchlist of large DOU service companies.",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resolve-careers", action="store_true")
    args = parser.parse_args(argv)
    try:
        path = workspace_path(args.output) if args.output is not None else default_service_ratings_path(ROOT)
    except ValueError as error:
        parser.error(str(error))
    existing_companies = []
    if path.exists():
        try:
            existing_payload = json.loads(path.read_text(encoding="utf-8"))
            existing_companies = existing_payload.get("companies", [])
        except (OSError, json.JSONDecodeError):
            pass

    companies = fetch_service_ratings()
    overrides = load_career_overrides()
    sites_resolved = 0
    careers_resolved = 0
    if args.resolve_careers:
        sites_resolved, careers_resolved = enrich_official_urls(companies, overrides=overrides)
    top50_added = merge_top50_companies(
        companies,
        fetch_top50(),
        career_urls=overrides,
    )
    manual_added = merge_manual_companies(companies, load_manual_additions())
    preserve_watchlist_state(companies, existing_companies)
    by_band: dict[str, int] = {}
    for company in companies:
        band = str(company.get("size_band") or "unknown")
        by_band[band] = by_band.get(band, 0) + 1

    summary = " ".join(f"{band}={count}" for band, count in by_band.items())
    print(f"DOU service watchlist: total={len(companies)} {summary}".rstrip())
    print(f"DOU Top 50 additions with verified career URLs: {top50_added}")
    print(f"Manual additions with official career URLs: {manual_added}")
    if args.resolve_careers:
        final_career_count = sum(bool(company.get("career_url")) for company in companies)
        print(
            f"Official URLs: rating_sites={sites_resolved} "
            f"careers={final_career_count}/{len(companies)}"
        )
    if args.dry_run:
        return 0

    save_service_ratings(path, companies)
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
