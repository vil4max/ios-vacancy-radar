#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.dou_catalog import (
    apply_site_enrichment,
    default_seed_path,
    discover_companies,
    load_seed,
    make_session,
    merge_seed,
    save_seed,
)
from config.paths import workspace_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh database/dou_companies.json from the DOU companies catalog.",
    )
    parser.add_argument(
        "--seed-path",
        type=Path,
        default=None,
        help="Seed JSON path (default: database/dou_companies.json)",
    )
    parser.add_argument(
        "--enrich-sites",
        action="store_true",
        help="Fetch DOU company profiles to fill missing site_url values",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Stop after N catalog pages (index + xhr pages)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Keep at most N companies after discovery (debug)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and print summary without writing the seed file",
    )
    args = parser.parse_args(argv)

    try:
        path = workspace_path(args.seed_path) if args.seed_path is not None else default_seed_path(ROOT)
    except ValueError as error:
        parser.error(str(error))
    session = make_session()
    discovered = discover_companies(
        session,
        max_pages=args.max_pages,
        limit=args.limit,
    )

    site_filled = 0
    if args.enrich_sites:
        site_filled = apply_site_enrichment(discovered, session, only_missing=True)

    old = load_seed(path)
    seed, stats = merge_seed(old, discovered)
    stats["site_filled"] = site_filled
    stats["discovered"] = len(discovered)

    print(
        "DOU catalog discovery:"
        f" discovered={stats['discovered']}"
        f" added={stats['added']}"
        f" updated={stats['updated']}"
        f" unchanged={stats['unchanged']}"
        f" site_filled={stats['site_filled']}"
        f" total={stats['total']}"
    )

    if args.dry_run:
        print(f"Dry run — not writing {path}")
        return 0

    save_seed(path, seed)
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
