"""Collection statistics passed from the pipeline to the digest."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceFailure:
    name: str
    url: str
    reason: str


@dataclass(frozen=True)
class CollectReportStats:
    found: int
    seen_total: int
    new_count: int
    duplicates_removed: int
    failed_source_names: tuple[str, ...] = ()
    sites_ok: int = 0
    sites_total: int = 0
    telegram_ok: int = 0
    telegram_total: int = 0
    telegram_skipped: int = 0
    # Channels not read because the reader credentials are missing.
    telegram_skipped_names: tuple[str, ...] = ()
    telegram_ok_names: tuple[str, ...] = ()
    degraded_source_names: tuple[str, ...] = ()
    failed_sources: tuple[SourceFailure, ...] = ()
    # Sites that answer but refuse automated access; they need a manual look, not a fix.
    manual_check_sources: tuple[SourceFailure, ...] = ()
    manual_review_roles: tuple[SourceFailure, ...] = ()
