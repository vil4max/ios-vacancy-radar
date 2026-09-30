from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlparse

from collector.types import STATUS_FAILED, STATUS_HEALTHY, SourceResult


def source_id_for(company: str, source_url: str | None = None) -> str:
    base = f"company:{company.strip().lower()}"
    host = urlparse(source_url or "").netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return f"{base}@{host}" if host else base


def source_ok(
    company: str,
    source_url: str,
    jobs: list[dict[str, Any]],
    started: float,
    *,
    scanned: int | None = None,
    source_id: str | None = None,
    empty_is_healthy: bool = False,
) -> SourceResult:
    return SourceResult(
        source_id=source_id or source_id_for(company, source_url),
        source_name=company,
        source_url=source_url,
        jobs=jobs,
        status=STATUS_HEALTHY,
        error=None,
        response_ms=int((time.perf_counter() - started) * 1000),
        items_scanned=len(jobs) if scanned is None else scanned,
        empty_is_healthy=empty_is_healthy,
    )


_ACCESS_BLOCKED = re.compile(r"(?i)\bHTTP 403\b|\b403 Client Error\b|anti-bot challenge")


def is_access_blocked(error: object) -> bool:
    """The site answered, but refuses automated clients; retries will not help."""
    return bool(_ACCESS_BLOCKED.search(str(error or "")))


def source_failed(
    company: str,
    source_url: str,
    error: Exception | str,
    started: float,
    *,
    source_id: str | None = None,
) -> SourceResult:
    return SourceResult(
        source_id=source_id or source_id_for(company, source_url),
        source_name=company,
        source_url=source_url,
        jobs=[],
        status=STATUS_FAILED,
        error=str(error),
        response_ms=int((time.perf_counter() - started) * 1000),
        items_scanned=0,
    )
