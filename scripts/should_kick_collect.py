#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.schedule import (
    COLLECT_HOURS,
    COLLECT_KICK_LAG_MINUTES,
    _as_kyiv,
    due_collect_slot,
    due_collect_slot_for_local_kick,
)
from storage.collect_slots import default_collect_slots_path, slot_completed
from planner.collect_health import report_overdue_slots


def _evaluate_gate() -> int:
    stamp = _as_kyiv()
    report_overdue_slots(default_collect_slots_path(ROOT), stamp)
    due = due_collect_slot(stamp)
    kick_due = due_collect_slot_for_local_kick(stamp)
    day = stamp.strftime("%Y-%m-%d")
    print(f"kyiv_hour={stamp.hour}")
    print(f"kyiv_minute={stamp.minute}")
    print(f"due_slot={due if due is not None else ''}")
    print(f"kick_slot={kick_due if kick_due is not None else ''}")
    print(f"kick_lag_minutes={COLLECT_KICK_LAG_MINUTES}")
    if due is None or stamp.hour >= 21:
        print(f"Local kick: outside Kyiv {COLLECT_HOURS[0]:02d}:00–21:00 — skip")
        return 1
    if kick_due is None:
        print(
            f"Local kick: waiting until Kyiv {due:02d}:{COLLECT_KICK_LAG_MINUTES:02d} — skip"
        )
        return 1
    path = default_collect_slots_path(ROOT)
    if slot_completed(path, day, kick_due):
        print(f"Local kick: Kyiv slot {kick_due:02d} already completed — skip")
        return 1
    slots = "/".join(f"{hour:02d}" for hour in COLLECT_HOURS)
    print(f"Local kick: Kyiv {slots} — dispatch Collect for slot {kick_due:02d}")
    return 0


def main() -> int:
    try:
        return _evaluate_gate()
    except Exception as error:
        print(f"Local kick gate failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
