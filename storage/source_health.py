from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from collector.types import STATUS_DEGRADED, STATUS_FAILED, STATUS_HEALTHY, SourceResult


def default_baseline_path(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parents[1]
    return base / "database" / "source_baseline.json"


def load_baseline(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def save_baseline(path: Path, baseline: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = dict(sorted(baseline.items(), key=lambda item: item[0]))
    path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# Records written before the policy was stored came from the iOS+AI search.
_LEGACY_SEARCH_POLICY = "ios+ai"


def current_search_policy() -> str:
    return "ios"


def best_scanned(baseline: dict[str, dict[str, Any]], source_id: str) -> int:
    record = baseline.get(source_id) or {}
    # A narrower search legitimately scans fewer items; the old best cannot prove breakage.
    if record.get("search_policy", _LEGACY_SEARCH_POLICY) != current_search_policy():
        return 0
    try:
        return int(record.get("best_scanned", 0) or 0)
    except (TypeError, ValueError):
        return 0


def empty_runs(baseline: dict[str, dict[str, Any]], source_id: str) -> int:
    record = baseline.get(source_id) or {}
    try:
        return int(record.get("empty_runs", 0) or 0)
    except (TypeError, ValueError):
        return 0


_DEGRADED_DROP_RATIO = 0.4
_DEGRADED_MIN_BEST = 8
_DEGRADED_EMPTY_RUNS = 3


def classify_degraded(
    results: list[SourceResult],
    baseline: dict[str, dict[str, Any]],
) -> list[str]:
    """Downgrade sources that used to return items but now return none.

    A collector that parses zero items while its baseline proves it once parsed
    many is almost always a broken selector, not an empty job board.
    """
    degraded: list[str] = []
    for result in results:
        if result.status != STATUS_HEALTHY:
            continue
        if result.items_scanned == 0 and result.empty_is_healthy:
            continue
        best = best_scanned(baseline, result.source_id)
        previous_empty_runs = empty_runs(baseline, result.source_id)
        if result.items_scanned == 0 and best > 0:
            result.status = STATUS_DEGRADED
            result.error = result.error or "parsed 0 items but previously parsed items"
            degraded.append(result.source_name)
            continue
        if result.items_scanned == 0 and previous_empty_runs >= _DEGRADED_EMPTY_RUNS - 1:
            result.status = STATUS_DEGRADED
            result.error = result.error or f"parsed 0 items for {previous_empty_runs + 1} runs"
            degraded.append(result.source_name)
            continue
        if best >= _DEGRADED_MIN_BEST and result.items_scanned < best * _DEGRADED_DROP_RATIO:
            result.status = STATUS_DEGRADED
            result.error = (
                result.error
                or f"parsed {result.items_scanned} items but previously parsed {best}"
            )
            degraded.append(result.source_name)
    return degraded


def update_baseline(
    baseline: dict[str, dict[str, Any]],
    results: list[SourceResult],
    *,
    now: str | None = None,
) -> dict[str, dict[str, Any]]:
    stamp = now or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    updated = dict(baseline)
    for result in results:
        if result.status == STATUS_FAILED:
            continue
        record = dict(updated.get(result.source_id) or {})
        record["name"] = result.source_name
        record["search_policy"] = current_search_policy()
        record["best_scanned"] = max(best_scanned(baseline, result.source_id), result.items_scanned)
        record["last_scanned"] = result.items_scanned
        record["last_success_at"] = stamp
        record["empty_runs"] = empty_runs(updated, result.source_id) + 1 if result.items_scanned == 0 else 0
        if result.items_scanned > 0:
            record["last_nonzero"] = stamp
        updated[result.source_id] = record
    return updated
