from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from collector.bespoke import (
    collect_andersen,
    collect_ciklum,
    collect_dataart,
    collect_globallogic,
    collect_grid_dynamics,
    collect_infopulse,
    collect_intellias,
    collect_luxoft,
    collect_mind_studios,
    collect_mwdn,
    collect_nix_html,
    collect_nortal,
    collect_onix,
    collect_rbi,
    collect_sigma,
    collect_softserve,
    collect_zone3000,
)
from collector.dou_rss import collect_dou_ai_rss, collect_dou_ios_rss
from collector.epam import collect_epam
from collector.hirify import collect_hirify
from collector.company_watchlist import collect_watchlist_company, load_company_watchlist
from collector.telegram_channels import collect_telegram_channels
from collector.types import STATUS_FAILED, CollectResult, SourceResult

_WATCHLIST_BESPOKE_COLLECTORS = (
    ("epam-systems", collect_epam),
    ("softserve", collect_softserve),
    ("globallogic", collect_globallogic),
    ("luxoft", collect_luxoft),
    ("ciklum", collect_ciklum),
    ("dataart", collect_dataart),
    ("intellias", collect_intellias),
    ("n-ix", collect_nix_html),
    ("sigma-software", collect_sigma),
    ("andersen", collect_andersen),
    ("zone3000", collect_zone3000),
    ("grid-dynamics", collect_grid_dynamics),
    ("nortal", collect_nortal),
    ("infopulse", collect_infopulse),
    ("onix-systems", collect_onix),
    ("rbi", collect_rbi),
    ("mind-studios", collect_mind_studios),
    ("mwdn", collect_mwdn),
)
_BESPOKE_WATCHLIST_SLUGS = frozenset(slug for slug, _collector in _WATCHLIST_BESPOKE_COLLECTORS)


def _watchlist_collectors() -> list[Callable[[], SourceResult]]:
    collectors: list[Callable[[], SourceResult]] = []
    for company in load_company_watchlist():
        if not bool(company.get("enabled", True)):
            continue
        slug = str(company.get("slug") or "")
        if slug in _BESPOKE_WATCHLIST_SLUGS:
            continue

        def collect(company: dict = company) -> SourceResult:
            return collect_watchlist_company(company)

        collect.__name__ = f"collect_watchlist_{slug.replace('-', '_')}"
        collectors.append(collect)
    return collectors


def _python_collectors() -> list[Callable[[], SourceResult]]:
    enabled_by_slug = {
        str(company.get("slug") or ""): bool(company.get("enabled", True))
        for company in load_company_watchlist()
    }
    bespoke_collectors = [
        collector
        for slug, collector in _WATCHLIST_BESPOKE_COLLECTORS
        if enabled_by_slug.get(slug, True)
    ]
    return bespoke_collectors + _watchlist_collectors() + [collect_hirify, collect_dou_ios_rss, collect_dou_ai_rss]


def _crashed_collector_result(collector: Callable[[], SourceResult], error: Exception) -> SourceResult:
    name = collector.__name__.removeprefix("collect_").replace("_", " ").title()
    return SourceResult(
        source_id=f"collector-crash:{collector.__name__}",
        source_name=name,
        source_url=None,
        jobs=[],
        status=STATUS_FAILED,
        error=str(error),
        response_ms=0,
        items_scanned=0,
    )


def collect_all(*, max_workers: int = 12) -> CollectResult:
    results: list[SourceResult] = []
    collectors = _python_collectors()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(collector): collector for collector in collectors}
        for future in as_completed(futures):
            collector = futures[future]
            try:
                results.append(future.result())
            except Exception as error:  # noqa: BLE001
                results.append(_crashed_collector_result(collector, error))

    results.extend(collect_telegram_channels())
    return CollectResult(source_results=results)
