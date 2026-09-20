from __future__ import annotations

from pathlib import Path

from storage.collect_slots import (
    load_collect_slots,
    mark_slot_completed,
    slot_completed,
)


def test_mark_and_query_slots(tmp_path: Path) -> None:
    path = tmp_path / "collect_slots.json"
    assert slot_completed(path, "2026-07-31", 9) is False
    assert mark_slot_completed(path, "2026-07-31", 9) is True
    assert slot_completed(path, "2026-07-31", 9) is True
    assert mark_slot_completed(path, "2026-07-31", 9) is False
    assert mark_slot_completed(path, "2026-07-31", 12) is True
    data = load_collect_slots(path)
    assert data["days"]["2026-07-31"]["slots"] == [9, 12]
