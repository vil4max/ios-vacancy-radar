"""Suppress outbound message previews in public workflow logs."""
from __future__ import annotations

import os


def logs_are_public() -> bool:
    return os.environ.get("GITHUB_ACTIONS", "").strip().lower() == "true"


def print_private(message: str) -> None:
    """Print local message previews only where the log is not published."""
    if logs_are_public():
        return
    print(message)
