from __future__ import annotations

import json
import os
from pathlib import Path


def default_telegram_cursors_path(root: Path | None = None) -> Path:
    override = os.environ.get("TELEGRAM_CURSORS_PATH", "").strip()
    if override:
        return Path(override)
    base = root or Path(__file__).resolve().parents[1]
    return base / "database" / "telegram_cursors.json"


def load_telegram_cursors(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return {
        str(key): int(value)
        for key, value in data.items()
        if isinstance(value, int) and value > 0
    }


def save_telegram_cursors(path: Path, cursors: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = dict(sorted(cursors.items(), key=lambda item: item[0]))
    path.write_text(json.dumps(ordered, indent=2) + "\n", encoding="utf-8")


def apply_cursor_updates(cursors: dict[str, int], updates: dict[str, int]) -> bool:
    changed = False
    for channel, message_id in updates.items():
        if message_id <= cursors.get(channel, 0):
            continue
        cursors[channel] = message_id
        changed = True
    return changed
