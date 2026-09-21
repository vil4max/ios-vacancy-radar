from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


STATUS_HEALTHY = "healthy"
STATUS_DEGRADED = "degraded"
STATUS_FAILED = "failed"


@dataclass
class SourceResult:
    source_id: str
    source_name: str
    source_url: str | None
    jobs: list[dict[str, Any]]
    status: str
    error: str | None
    response_ms: int
    items_scanned: int = 0
    empty_is_healthy: bool = False
    checkpoint: int | None = None
    # Items read but not parseable; the source stays usable and reports the count.
    items_skipped: int = 0
    # Target roles whose detail page rejected automated access; shown for manual review.
    manual_review: list[dict[str, str]] = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        return self.status != STATUS_FAILED


@dataclass
class CollectResult:
    source_results: list[SourceResult]
