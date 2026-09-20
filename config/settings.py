from __future__ import annotations

import os


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def seen_gate_enabled() -> bool:
    """The seen gate reports a vacancy once. Turning it off re-announces every
    collected vacancy on each run, which is only useful when debugging delivery.
    The variable keeps its legacy name so an existing deployment keeps working."""
    return _env_bool("CAREER_AGENT_SEEN_GATE", default=True)
