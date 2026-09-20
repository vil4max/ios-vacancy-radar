#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.schedule import COLLECT_HOURS, _as_kyiv, due_collect_slot
from storage.collect_slots import default_collect_slots_path, slot_completed
from planner.collect_health import report_overdue_slots


def _evaluate_gate() -> int:
    stamp = _as_kyiv()
    report_overdue_slots(default_collect_slots_path(ROOT), stamp)
    due = due_collect_slot(stamp)
    day = stamp.strftime("%Y-%m-%d")
    print(f"kyiv_hour={stamp.hour}")
    print(f"due_slot={due if due is not None else ''}")
    if due is None:
        print(f"Collect window: before Kyiv {COLLECT_HOURS[0]:02d}:00 — skip")
        return 1
    path = default_collect_slots_path(ROOT)
    if slot_completed(path, day, due):
        print(f"Collect window: Kyiv slot {due:02d} already completed — skip")
        return 1
    slots = "/".join(f"{hour:02d}" for hour in COLLECT_HOURS)
    print(f"Collect window: Kyiv {slots} — run due slot {due:02d}")
    return 0


def main() -> int:
    try:
        return _evaluate_gate()
    except Exception as error:
        print(f"Collect schedule gate failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
