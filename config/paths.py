from __future__ import annotations

import os
from pathlib import Path


def workspace_path(value: str | Path, *, base: Path | None = None) -> Path:
    """Confine CLI paths to the working directory, including symlink targets."""
    root = Path(base or Path.cwd()).resolve()
    raw = Path(value)
    resolved = (root / raw).resolve() if not raw.is_absolute() else raw.resolve()
    try:
        common = Path(os.path.commonpath([str(root), str(resolved)]))
    except ValueError:
        raise ValueError("Path must stay within the working directory") from None
    if common != root or not resolved.is_relative_to(root):
        raise ValueError("Path must stay within the working directory")
    return resolved
