from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from config.schedule import COLLECT_HOURS, COLLECT_KICK_LAG_MINUTES, _as_kyiv
from storage.collect_slots import load_collect_slots


def overdue_slots(path: Path, now: datetime | None = None) -> list[int]:
    stamp = _as_kyiv(now)
    entry = load_collect_slots(path)["days"].get(stamp.date().isoformat(), {})
    completed = {int(value) for value in entry.get("slots", [])}
    return [hour for hour in COLLECT_HOURS if hour not in completed and stamp >=
            stamp.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(minutes=COLLECT_KICK_LAG_MINUTES)]


def report_overdue_slots(path: Path, now: datetime | None = None) -> None:
    slots = overdue_slots(path, now)
    message = "Overdue Kyiv collect slots: " + (", ".join(f"{hour:02d}:00" for hour in slots) or "none")
    print(message)
    if slots and os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning title=Collection schedule::{message}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(message + "\n")


LATE_ALERT_MINUTES = 60


def late_slots(path: Path, now: datetime | None = None, *, minutes: int = LATE_ALERT_MINUTES) -> list[tuple[int, int]]:
    """Today's uncompleted slots that started at least `minutes` ago, with their lag in minutes."""
    stamp = _as_kyiv(now)
    late: list[tuple[int, int]] = []
    for hour in overdue_slots(path, stamp):
        lag = int((stamp - stamp.replace(hour=hour, minute=0, second=0, microsecond=0)).total_seconds() // 60)
        if lag >= minutes:
            late.append((hour, lag))
    return late
