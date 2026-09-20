"""Publish allowlisted runtime JSON without rebasing the running checkout.

State does not have to live in this repository. `--root` points the git side of
a refresh or publish at another checkout, so a store that must stay private --
the vacancy discovery history in database/seen.json -- is read from and pushed
to that repository while the public state stays here. Diagnostics and the
snapshot stay in the working directory either way.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PATHS = frozenset({
    "database/seen.json", "database/source_baseline.json",
    "database/telegram_cursors.json", "database/collect_slots.json",
    "database/vacancy_feed.json",
})
# Search results. They may be refreshed or published only through --root, into
# the private store, and never in the checkout of this public repository.
PRIVATE_ONLY = frozenset({"database/seen.json", "database/vacancy_feed.json"})
HISTORY = {"database/seen.json"}


def public_state(path: str, value):
    """Strip private fields from every version so a stale base or run cannot restore them."""
    if path == "database/seen.json" and isinstance(value, dict):
        from storage.seen import sanitize_seen

        return sanitize_seen(value)
    return value
MISSING = object()


class StateConflict(ValueError):
    pass


def merge_state(base, local, remote, path: str, keys: tuple[str, ...] = ()):
    """Merge independent edits; never silently choose between conflicting decisions."""
    values = [v for v in (base, local, remote) if v is not MISSING]
    if path == "database/telegram_cursors.json" and len(keys) == 1:
        if not all(type(v) is int and v >= 0 for v in values):
            raise StateConflict(f"Invalid cursor: {path}")
        return max(values)
    if path == "database/collect_slots.json" and len(keys) == 3 and keys[-1] == "slots":
        if not all(isinstance(v, list) for v in values):
            raise StateConflict(f"Invalid claim list: {path}")
        items = [item for value in values for item in value]
        expected_type = int
        if not all(type(item) is expected_type for item in items):
            raise StateConflict(f"Invalid claim value: {path}")
        return sorted(set(items))
    if all(isinstance(v, dict) for v in values):
        result = {}
        for key in sorted(set().union(*(v.keys() for v in values))):
            before, ours, theirs = (v.get(key, MISSING) if isinstance(v, dict) else MISSING for v in (base, local, remote))
            # Vacancy discovery history is append-only at the record level, even after pruning.
            if path in HISTORY and not keys:
                ours = before if ours is MISSING and before is not MISSING else ours
                theirs = before if theirs is MISSING and before is not MISSING else theirs
            merged = merge_state(before, ours, theirs, path, (*keys, key))
            if merged is not MISSING:
                result[key] = merged
        return result
    if local == remote:
        return local
    if local == base:
        return remote
    if remote == base:
        return local
    # Do not include keys/values: private identifiers are private.
    raise StateConflict(f"Concurrent field conflict in {path} (depth {len(keys)})")


def git(root: Path, *args: str, data: bytes | None = None, env=None) -> bytes:
    return subprocess.run(["git", *args], cwd=root, input=data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True, env=env).stdout


def fetch(root: Path) -> str:
    git(root, "fetch", "origin", "refs/heads/main")
    return git(root, "rev-parse", "FETCH_HEAD").decode().strip()


def read_state(root: Path, revision: str, path: str):
    entry = git(root, "ls-tree", revision, "--", path)
    if not entry:
        return {}
    value = json.loads(git(root, "show", f"{revision}:{path}"))
    if not isinstance(value, dict):
        raise StateConflict(f"Expected JSON object: {path}")
    return public_state(path, value)


def encode(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


SNAPSHOT_FILENAMES = frozenset({
    "runtime-state-base.json",
    "base.json",
    "snapshot.json",
})


def validate_paths(paths, root: Path | None = None, work: Path | None = None):
    if not paths or not set(paths) <= PATHS:
        raise ValueError("Only allowlisted runtime paths can be refreshed or published")
    # `work` is the checkout the command runs in. A caller that names it and
    # points the store at the same place is about to publish a search result
    # into this public repository.
    if work is not None and set(paths) & PRIVATE_ONLY:
        if Path(root or work).resolve() == Path(work).resolve():
            raise ValueError("Private-only state needs a separate --root store")


def diagnostics_dir(work: Path) -> Path:
    base = Path(work).resolve()
    diag_dir = (base / "diagnostics").resolve()
    if not diag_dir.is_relative_to(base) or os.path.commonpath([str(base), str(diag_dir)]) != str(base):
        raise ValueError("Diagnostics directory must stay within the working directory")
    return diag_dir


def validate_snapshot_path(snapshot: Path | str, root: Path | None = None) -> Path:
    base = Path(root or Path.cwd()).resolve()
    diag_dir = diagnostics_dir(base)
    raw = Path(snapshot)
    if raw.name not in SNAPSHOT_FILENAMES:
        raise ValueError("Snapshot filename must be an allowlisted snapshot name")
    safe_target = (diag_dir / raw.name).resolve()
    candidate = (base / raw).resolve() if not raw.is_absolute() else raw.resolve()
    if candidate != safe_target or not safe_target.is_relative_to(diag_dir):
        raise ValueError("Snapshot must stay directly within the diagnostics directory")
    return safe_target


def resolve_snapshot(snapshot: Path | str | None, work: Path) -> Path:
    diag_dir = diagnostics_dir(work)
    if snapshot is None:
        return (diag_dir / "runtime-state-base.json").resolve()
    return validate_snapshot_path(snapshot, root=work)


def state_target(root: Path, path: str) -> Path:
    """Allowlisted runtime file inside the store that owns it."""
    base = Path(root).resolve()
    if path not in PATHS:
        raise ValueError("Only allowlisted runtime paths can be refreshed or published")
    target = (base / path).resolve()
    if not target.is_relative_to(base) or os.path.commonpath([str(base), str(target)]) != str(base):
        raise ValueError("Path must stay within the state directory")
    return target


def refresh(root: Path, paths: list[str], snapshot: Path | None = None, work: Path | None = None) -> str:
    """Replace the allowlisted files under `root` with the published state of
    that store, without touching anything else in the checkout."""
    validate_paths(paths, root, work)
    snapshot_target = resolve_snapshot(snapshot, work or root)
    # Validate the whole batch before replacing any state. Source code stays pinned.
    targets = {path: state_target(root, path) for path in paths}
    revision = fetch(root)

    states = {path: read_state(root, revision, path) for path in paths}
    for path, state in states.items():
        target = targets[path]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encode(state))
    snapshot_target.parent.mkdir(parents=True, exist_ok=True)
    snapshot_target.write_bytes(encode({"base": revision, "paths": paths}))
    return revision


def publish(root: Path, snapshot: Path | None = None, message: str = "chore(state): persist runtime state [skip ci]", attempts: int = 5, work: Path | None = None) -> str | None:
    snapshot_target = resolve_snapshot(snapshot, work or root)

    metadata = json.loads(snapshot_target.read_bytes())
    paths = metadata["paths"]
    validate_paths(paths, root, work)
    base_state = {path: read_state(root, metadata["base"], path) for path in paths}
    local = {
        path: public_state(path, json.loads(state_target(root, path).read_bytes()))
        for path in paths
    }
    if not all(isinstance(value, dict) for value in local.values()):
        raise StateConflict("Runtime state must contain JSON objects")
    remote_revision = fetch(root)
    for _ in range(attempts):
        remote = {path: read_state(root, remote_revision, path) for path in paths}
        merged = {path: merge_state(base_state[path], local[path], remote[path], path) for path in paths}
        changed = {path: state for path, state in merged.items() if state != remote[path]}
        if not changed:
            return None
        with tempfile.TemporaryDirectory(prefix="career-state-") as temp:
            env = dict(os.environ, GIT_INDEX_FILE=str(Path(temp) / "index"),
                       GIT_AUTHOR_NAME="github-actions[bot]", GIT_COMMITTER_NAME="github-actions[bot]",
                       GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com",
                       GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com")
            git(root, "read-tree", remote_revision, env=env)
            for path, state in changed.items():
                blob = git(root, "hash-object", "-w", "--stdin", data=encode(state)).decode().strip()
                git(root, "update-index", "--add", "--cacheinfo", "100644", blob, path, env=env)
            tree = git(root, "write-tree", env=env).decode().strip()
            revision = git(root, "commit-tree", tree, "-p", remote_revision, "-m", message, env=env).decode().strip()
        try:
            git(root, "push", "origin", f"{revision}:refs/heads/main")
            return revision
        except subprocess.CalledProcessError:
            latest = fetch(root)
            if latest == remote_revision:
                raise
            remote_revision = latest
    raise StateConflict("Runtime state push races exhausted; recover from the workflow artifact")


def write_diagnostic(action: str, error_detail: str, root: Path | None = None) -> None:
    base = Path(root or Path.cwd()).resolve()
    target = (base / "diagnostics" / "runtime-state-error.json").resolve()
    if not target.is_relative_to(base) or os.path.commonpath([str(base), str(target)]) != str(base):
        print("Could not write the local recovery diagnostic")
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encode({"action": action, "error": error_detail, "recovery": "Use the state recovery artifact"}))
    except (ValueError, OSError):
        print("Could not write the local recovery diagnostic")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("refresh", "publish"))
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--snapshot", type=Path, default=None)
    parser.add_argument("--message", default="chore(state): persist runtime state [skip ci]")
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Checkout that owns this state; defaults to the working directory. "
             "A store that must stay private lives in its own repository.",
    )
    args = parser.parse_args()
    work = Path.cwd().resolve()
    try:
        snapshot = resolve_snapshot(args.snapshot, work)
        root = work if args.root is None else Path(args.root).resolve()
        if not (root / ".git").exists():
            raise ValueError("State root must be a git checkout")
    except ValueError as error:
        print(f"Runtime state {args.action} failed: {type(error).__name__}")
        return 1

    try:
        if args.action == "refresh":
            print("Runtime state refreshed:", refresh(root, args.paths, snapshot, work=work))
        else:
            print("Runtime state published:", publish(root, snapshot, args.message, work=work) or "unchanged")
    except (StateConflict, ValueError, OSError, subprocess.CalledProcessError) as error:
        # Avoid echoing subprocess arguments/output or JSON data from private state.
        detail = str(error) if isinstance(error, StateConflict) else type(error).__name__
        write_diagnostic(args.action, detail, root=Path.cwd())
        print(f"Runtime state {args.action} failed: {detail}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
