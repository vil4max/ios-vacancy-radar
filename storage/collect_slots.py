from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def default_collect_slots_path(root: Path | None = None) -> Path:
    override = os.environ.get("COLLECT_SLOTS_PATH", "").strip()
    if override:
        return Path(override)
    base = root or Path(__file__).resolve().parents[1]
    return base / "database" / "collect_slots.json"


def load_collect_slots(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"days": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"days": {}}
    days = data.get("days")
    if not isinstance(days, dict):
        data["days"] = {}
    return data


def save_collect_slots(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    days = data.get("days") if isinstance(data.get("days"), dict) else {}
    ordered_days = {
        day: {
            "slots": sorted({int(slot) for slot in (entry.get("slots") or []) if str(slot).isdigit() or isinstance(slot, int)}),
        }
        for day, entry in sorted(days.items())
        if isinstance(entry, dict)
    }
    payload = {"days": ordered_days}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def slot_completed(path: Path, day: str, slot: int) -> bool:
    data = load_collect_slots(path)
    entry = (data.get("days") or {}).get(day) or {}
    slots = entry.get("slots") or []
    return int(slot) in {int(value) for value in slots}


def mark_slot_completed(path: Path, day: str, slot: int) -> bool:
    data = load_collect_slots(path)
    days = data.setdefault("days", {})
    entry = days.setdefault(day, {"slots": []})
    slots = {int(value) for value in (entry.get("slots") or [])}
    if int(slot) in slots:
        return False
    slots.add(int(slot))
    entry["slots"] = sorted(slots)
    save_collect_slots(path, data)
    return True
