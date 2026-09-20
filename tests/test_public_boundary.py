"""Guard the public/private boundary of the (public) ios-vacancy-radar repository.

Committed state must never carry personal application decisions or mail
content, and committed docs must never carry personal pipeline facts (interview
outcomes, funnel counts, rejections by company). Commit messages are checked
too: they are published with the tree and cannot be edited once pushed. See
docs/operations.md, the AGENTS.md boundary rules, and the 2026-09-15 privacy
audit. Private career storage owns that content; this repository only collects
public vacancies.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

_SEEN_ALLOWED_FIELDS = frozenset({"title", "company", "first_seen"})

# Markers that only show up if a personal outcome or identity leaked into a
# committed doc. Each is narrow and named so a false positive is easy to place
# and fix at the source instead of loosening the whole guard.
_PERSONAL_DOC_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("interview score pattern", re.compile(r"(?i)\b(?:coding|theory)\s+\d{1,2}/10\b")),
    ("leveling grade outcome", re.compile(r"(?i)\bgraded\s+t\d\b|\bprior\s+t\d\b")),
    ("funnel outcome count", re.compile(r"(?i)\byour funnel\b")),
    ("personal outcome diary reference", re.compile(r"(?i)\bprofile diary\b")),
    ("first-person application history", re.compile(
        r"(?i)\bmy (?:interview|application|rejection|resume|cv|offer)\b"
    )),
    ("re-apply advice tied to a past attempt", re.compile(r"(?i)\bdo not re-apply\b")),
    # The owner's own pay is the costliest leak. The markers require personal
    # framing: a salary printed in a public posting is a public vacancy fact,
    # and the policy vocabulary ("compensation expectations" in a rule, DOU's
    # compensation rating) is not data either.
    ("personal pay reference", re.compile(
        r"(?i)\b(?:my|owner'?s)\s+(?:salary|compensation|rate|offer|comp)\b"
    )),
    ("pay expectation value", re.compile(
        r"(?i)\b(?:salary|compensation|rate|comp)\s+(?:expectation|target|range|band)s?\s*[:=]"
    )),
    ("pay expectation in Russian or Ukrainian", re.compile(
        r"(?i)\u0437\u0430\u0440\u043f\u043b\u0430\u0442\u043d\w*\s+(?:\u043e\u0436\u0438\u0434\u0430\u043d\u0438|\u043e\u0447\u0456\u043a\u0443\u0432\u0430\u043d\u043d)\w*"
    )),
    ("interview outcome", re.compile(
        r"(?i)\b(?:interview|screening|tech\s+screen)\s+(?:feedback|notes?|debrief|outcome|result)s?\b"
        r"|\b(?:\u043f\u043e\s+\u0438\u0442\u043e\u0433\u0430\u043c|\u043f\u043e\u0441\u043b\u0435)\s+\u0441\u043e\u0431\u0435\u0441\w*"
    )),
    ("offer terms", re.compile(
        r"(?i)\boffer\s+(?:accepted|declined|received|terms)\b|\bcounter[- ]offer\b"
    )),
)

# Reports and docs are allowed to discuss the CRM's own close-reason vocabulary
# (e.g. "Rejected HR" as a Project field option) — that names a schema, not an
# outcome — so the markers above stay specific rather than matching "reject".

_MD_DIRS = ("reports", "docs")

# Identity markers are matched by shape, not by value: naming the owner's real
# address or board id here would publish the very thing the guard defends.
_IDENTITY_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "personal mailbox address",
        re.compile(
            r"(?<![A-Za-z0-9._%+-])(?!(?:you|owner|user|example)@)"
            r"[A-Za-z0-9._%+-]+@(?:gmail|googlemail)\.com"
        ),
    ),
    ("GitHub Project node id", re.compile(r"\bPVT(?:SSF|F)?_[A-Za-z0-9]{10,}")),
    (
        "personal Project board URL",
        re.compile(
            r"github\.com/users/(?!(?:you|owner|acme|example|user|org|me|login|x)/)"
            r"[^/\s)]+/projects/\d+"
        ),
    ),
)

_PLACEHOLDER_LOGINS = "you, owner, acme, example, user, org, me, login, x"

_SCANNED_SUFFIXES = frozenset({".py", ".md", ".yml", ".yaml", ".sh", ".properties", ".txt"})

# Fixtures may name example.com addresses and an "owner/repo" placeholder; the
# markers above are narrow enough that those do not match.
_IDENTITY_EXEMPT = (Path("tests") / "test_public_boundary.py",)


def _tracked_markdown_files() -> list[Path]:
    files: list[Path] = []
    for directory in _MD_DIRS:
        base = ROOT / directory
        if base.is_dir():
            files.extend(sorted(base.rglob("*.md")))
    return files


def _tracked_text_files() -> list[Path]:
    import subprocess

    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    files = []
    for name in listing.split("\0"):
        if not name:
            continue
        relative = Path(name)
        if relative.suffix not in _SCANNED_SUFFIXES or relative in _IDENTITY_EXEMPT:
            continue
        if (ROOT / relative).is_file():
            files.append(relative)
    return sorted(files)



def test_search_results_are_not_tracked_in_this_repository() -> None:
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "database/seen.json", "database/vacancy_feed.json"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    assert not tracked, f"search results belong to the private store, not here: {tracked}"


def test_seen_store_never_keeps_an_application_decision() -> None:
    from storage.seen import sanitize_seen

    record = {"title": "iOS", "company": "Acme", "first_seen": "2026-01-01", "disposition": "applied",
              "applied_at": "2026-01-02"}
    cleaned = sanitize_seen({"https://acme.example/job": record})["https://acme.example/job"]
    assert set(cleaned) <= _SEEN_ALLOWED_FIELDS


@pytest.mark.parametrize("path", _tracked_markdown_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_markdown_report_has_no_personal_pipeline_marker(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    hits = [name for name, pattern in _PERSONAL_DOC_MARKERS if pattern.search(text)]
    assert not hits, f"{path.relative_to(ROOT)} contains personal pipeline markers: {hits}"


@pytest.mark.parametrize("relative", _tracked_text_files(), ids=str)
def test_tracked_file_has_no_personal_pipeline_marker(relative: Path) -> None:
    # A leak is not limited to prose: a code comment, a fixture or a workflow
    # carries just as far, and all of them are published together.
    text = (ROOT / relative).read_text(encoding="utf-8", errors="ignore")
    hits = [name for name, pattern in _PERSONAL_DOC_MARKERS if pattern.search(text)]
    assert not hits, (
        f"{relative} contains personal pipeline markers: {hits}. Interview outcomes, "
        "pay and application history belong on the private board, never in this repository."
    )


@pytest.mark.parametrize("relative", _tracked_text_files(), ids=str)
def test_tracked_file_carries_no_owner_identity(relative: Path) -> None:
    text = (ROOT / relative).read_text(encoding="utf-8", errors="ignore")
    hits = [name for name, pattern in _IDENTITY_MARKERS if pattern.search(text)]
    assert not hits, (
        f"{relative} hardcodes owner identity ({hits}); read it from the "
        f"environment instead — workflow logs and the tree are public. "
        f"Docs and fixtures may use the placeholder logins: {_PLACEHOLDER_LOGINS}"
    )


def _unpublished_commits() -> list[tuple[str, str]]:
    """Commits on HEAD that the published branch does not have yet. They are
    the last point at which a message can still be rewritten."""
    import subprocess

    upstream = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "origin/main"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if upstream.returncode != 0:
        return []
    listing = subprocess.run(
        ["git", "log", "origin/main..HEAD", "--format=%H%x1f%B%x1e"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if listing.returncode != 0:
        return []
    commits = []
    for record in listing.stdout.split("\x1e"):
        if "\x1f" not in record:
            continue
        sha, message = record.strip().split("\x1f", 1)
        commits.append((sha[:12], message))
    return commits


@pytest.mark.parametrize("sha,message", _unpublished_commits(), ids=lambda value: str(value)[:12])
def test_unpublished_commit_message_carries_no_personal_marker(sha: str, message: str) -> None:
    hits = [
        name
        for name, pattern in (*_PERSONAL_DOC_MARKERS, *_IDENTITY_MARKERS)
        if pattern.search(message)
    ]
    assert not hits, (
        f"commit {sha} has personal markers in its message: {hits}. "
        "Rewrite the message before pushing; a pushed message cannot be taken back."
    )


def _collect_workflow_step(name: str) -> str:
    text = (ROOT / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8")
    start = text.index(f"- name: {name}")
    remainder = text[start + 1:]
    end = remainder.find("\n      - name: ")
    return remainder if end == -1 else remainder[:end]


def test_recovery_artifact_never_uploads_the_private_state_store() -> None:
    step = _collect_workflow_step("Upload collection recovery state")
    offenders = [line.strip() for line in step.splitlines() if "seen.json" in line or "vacancy_feed" in line]
    assert not offenders, (
        "the collection recovery artifact of a PUBLIC repository is downloadable, so "
        f"search results must never be uploaded from here: {offenders}"
    )


def test_collection_has_no_public_fallback_for_search_results() -> None:
    text = (ROOT / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8")
    # Every reference to a search-result file must go through the private store.
    for line in text.splitlines():
        if "SEEN_PATH:" in line or "FEED_PATH:" in line:
            assert "state/" in line, line.strip()
    assert "Require the private state store" in text
