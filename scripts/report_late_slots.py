#!/usr/bin/env python3
"""Print an alert line for collect slots that are late, or nothing.

The cloud trigger runs this so a slot that the local catch-up agent could not
start (the Mac asleep or off) is reported instead of passing silently.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planner.collect_health import late_slots
from storage.collect_slots import default_collect_slots_path


def main() -> int:
    late = late_slots(default_collect_slots_path(ROOT))
    if late:
        slots = ", ".join(f"{hour:02d}:00 ({lag} min)" for hour, lag in late)
        print(f"Kyiv collect slot not started on time: {slots}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
