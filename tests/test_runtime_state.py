from __future__ import annotations

import json
import subprocess

import pytest

from scripts import runtime_state as state

SEEN = "database/seen.json"
CURSOR = "database/telegram_cursors.json"


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def write(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value))


def commit(root, message="test: change"):
    git(root, "add", ".")
    git(root, "commit", "-m", message)
    git(root, "push", "origin", "main")


def isolate_git(tmp_path, monkeypatch):
    # Fixture repositories must not inherit the owner's hooks or an enclosing push's repository.
    for name in git(tmp_path, "rev-parse", "--local-env-vars").splitlines():
        monkeypatch.delenv(name, raising=False)
    config = tmp_path / "gitconfig"
    config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def repos(tmp_path, monkeypatch):
    isolate_git(tmp_path, monkeypatch)
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare", "--initial-branch=main")
    work = tmp_path / "work"
    git(tmp_path, "clone", str(remote), str(work))
    git(work, "config", "user.name", "Test")
    git(work, "config", "user.email", "test@example.invalid")
    write(work, SEEN, {"old": {"company": "Acme", "title": "iOS"}})
    write(work, CURSOR, {"channel": 10})
    (work / "source.py").write_text("original\n")
    commit(work)
    other = tmp_path / "other"
    git(tmp_path, "clone", str(remote), str(other))
    git(other, "config", "user.name", "Test")
    git(other, "config", "user.email", "test@example.invalid")
    return work, other, remote


def test_git_isolation_ignores_host_config_and_enclosing_push(tmp_path, monkeypatch):
    host_config = tmp_path / "host-gitconfig"
    host_config.write_text("[core]\n\thooksPath = /host-only-hooks\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(host_config))
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "outside.git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "outside-index"))
    isolate_git(tmp_path, monkeypatch)
    git(tmp_path, "init", "--bare", "--initial-branch=main")
    config = git(tmp_path, "config", "--list", "--show-origin")
    assert "host-gitconfig" not in config
    assert "core.hookspath" not in config.lower()
    assert git(tmp_path, "rev-parse", "--absolute-git-dir") == str(tmp_path.resolve())
    assert host_config.read_text() == "[core]\n\thooksPath = /host-only-hooks\n"


def test_remote_source_commit_preserved_and_checkout_untouched(repos, tmp_path):
    work, other, remote = repos
    snapshot = work / "diagnostics/base.json"
    head = git(work, "rev-parse", "HEAD")
    state.refresh(work, [SEEN], snapshot)
    write(work, SEEN, {"old": {"company": "Acme", "title": "iOS"}, "ours": {"title": "AI"}})
    (work / "source.py").write_text("local unstaged work\n")
    staged = work / "staged.py"
    staged.write_text("local staged work\n")
    git(work, "add", "staged.py")
    index = git(work, "write-tree")
    (other / "source.py").write_text("new remote source\n")
    write(other, SEEN, {"old": {"company": "Acme", "title": "iOS"}, "theirs": {"title": "Swift"}})
    commit(other)
    published = state.publish(work, snapshot, "chore(state): test")
    assert git(remote, "show", "main:source.py") == "new remote source"
    result = json.loads(git(remote, "show", f"main:{SEEN}"))
    assert set(result) == {"old", "ours", "theirs"}
    assert git(work, "rev-parse", "HEAD") == head
    assert git(work, "write-tree") == index
    assert (work / "source.py").read_text() == "local unstaged work\n"
    assert git(remote, "rev-parse", "main") == published
    assert not git(remote, "ls-tree", "main", "--", "staged.py")


def test_conflicting_decisions_fail_without_overwriting_remote(repos, tmp_path):
    work, other, remote = repos
    snapshot = work / "diagnostics/base.json"
    state.refresh(work, [SEEN], snapshot)
    write(work, SEEN, {"old": {"company": "Acme", "title": "iOS Developer"}})
    write(other, SEEN, {"old": {"company": "Acme", "title": "iOS Engineer"}})
    commit(other)
    remote_head = git(remote, "rev-parse", "main")
    with pytest.raises(state.StateConflict, match="Concurrent field conflict"):
        state.publish(work, snapshot, "chore(state): test")
    assert git(remote, "rev-parse", "main") == remote_head


def test_history_retained_and_cursor_never_rewinds(repos, tmp_path):
    work, other, remote = repos
    snapshot = work / "diagnostics/base.json"
    state.refresh(work, [SEEN, CURSOR], snapshot)
    write(work, SEEN, {})
    write(work, CURSOR, {"channel": 20})
    write(other, CURSOR, {"channel": 30})
    commit(other)
    state.publish(work, snapshot, "chore(state): test")
    assert json.loads(git(remote, "show", f"main:{SEEN}"))["old"]["title"] == "iOS"
    assert json.loads(git(remote, "show", f"main:{CURSOR}")) == {"channel": 30}


def test_retry_remerges_when_push_loses_race(repos, tmp_path, monkeypatch):
    work, other, remote = repos
    snapshot = work / "diagnostics/base.json"
    state.refresh(work, [CURSOR], snapshot)
    write(work, CURSOR, {"channel": 20})
    actual_git = state.git
    pushes = []

    def raced_git(root, *args, **kwargs):
        if args[0] == "push":
            pushes.append(args)
            if len(pushes) == 1:
                write(other, CURSOR, {"channel": 30})
                commit(other)
        return actual_git(root, *args, **kwargs)

    monkeypatch.setattr(state, "git", raced_git)
    # The second merge becomes a no-op: the other writer advanced farther.
    assert state.publish(work, snapshot, "chore(state): test") is None
    assert len(pushes) == 1
    assert json.loads(git(remote, "show", f"main:{CURSOR}")) == {"channel": 30}


def test_push_permission_failure_is_not_retried(repos, tmp_path, monkeypatch):
    work, _, _ = repos
    snapshot = work / "diagnostics/base.json"
    state.refresh(work, [CURSOR], snapshot)
    write(work, CURSOR, {"channel": 20})
    actual_git = state.git
    pushes = []

    def rejected_git(root, *args, **kwargs):
        if args[0] == "push":
            pushes.append(args)
            raise subprocess.CalledProcessError(1, ["git", "push"])
        return actual_git(root, *args, **kwargs)

    monkeypatch.setattr(state, "git", rejected_git)
    with pytest.raises(subprocess.CalledProcessError):
        state.publish(work, snapshot, "chore(state): test")
    assert len(pushes) == 1






def test_allowlist_and_malformed_state_fail_closed(repos, tmp_path):
    work, _, _ = repos
    with pytest.raises(ValueError, match="allowlisted"):
        state.refresh(work, ["source.py"], work / "diagnostics/base.json")
    snapshot = work / "diagnostics/base.json"
    state.refresh(work, [SEEN], snapshot)
    (work / SEEN).write_text("[]")
    with pytest.raises(state.StateConflict, match="JSON objects"):
        state.publish(work, snapshot, "chore(state): test")


def test_refresh_reads_latest_state_without_switching_code(repos, tmp_path):
    work, other, _ = repos
    (other / "source.py").write_text("new source\n")
    write(other, CURSOR, {"channel": 99})
    commit(other)
    state.refresh(work, [CURSOR], work / "diagnostics/base.json")
    assert json.loads((work / CURSOR).read_text()) == {"channel": 99}
    assert (work / "source.py").read_text() == "original\n"


def test_cli_writes_safe_failure_artifact(repos, tmp_path, monkeypatch, capsys):
    work, _, _ = repos
    snapshot = work / "diagnostics/base.json"
    state.refresh(work, [CURSOR], snapshot)
    (work / CURSOR).write_text("private invalid json")
    monkeypatch.chdir(work)
    monkeypatch.setattr("sys.argv", ["runtime_state.py", "publish", "--snapshot", str(snapshot)])
    assert state.main() == 1
    diagnostic = (work / "diagnostics/runtime-state-error.json").read_text()
    assert "JSONDecodeError" in diagnostic
    assert "private invalid json" not in diagnostic + capsys.readouterr().out


def test_invalid_claim_values_rejected():
    with pytest.raises(state.StateConflict, match="Invalid claim value"):
        state.merge_state([], [{}], [], "database/collect_slots.json", ("days", "2026-09-19", "slots"))


def test_public_state_strips_application_decisions_from_seen():
    legacy = {"https://acme.example/job": {"title": "iOS", "company": "Acme", "disposition": "applied",
                                           "applied_at": "2026-09-01"}}
    assert state.public_state(SEEN, legacy) == {"https://acme.example/job": {"title": "iOS", "company": "Acme"}}


def test_private_store_publishes_to_its_own_repository(repos, tmp_path, monkeypatch):
    """seen.json can live outside this repository: --root moves the git side of
    the state to another checkout while diagnostics stay in the working one."""
    work, _, public_remote = repos
    public_head = git(public_remote, "rev-parse", "main")

    store_remote = tmp_path / "state-remote.git"
    store_remote.mkdir()
    git(store_remote, "init", "--bare", "--initial-branch=main")
    store = tmp_path / "state"
    git(tmp_path, "clone", str(store_remote), str(store))
    git(store, "config", "user.name", "Test")
    git(store, "config", "user.email", "test@example.invalid")
    write(store, SEEN, {"https://acme.example/one": {"company": "Acme", "title": "iOS"}})
    commit(store)

    snapshot = work / "diagnostics/base.json"
    state.refresh(store, [SEEN], snapshot, work=work)
    assert json.loads((store / SEEN).read_text()) == {
        "https://acme.example/one": {"company": "Acme", "title": "iOS"}
    }
    assert not (work / SEEN).exists() or json.loads((work / SEEN).read_text()) != json.loads(
        (store / SEEN).read_text()
    )
    assert snapshot.exists(), "the snapshot belongs to the working directory, not the store"

    seen = json.loads((store / SEEN).read_text())
    seen["https://acme.example/two"] = {"company": "Acme", "title": "Senior iOS"}
    write(store, SEEN, seen)
    assert state.publish(store, snapshot, work=work) is not None

    published = json.loads(
        subprocess.run(["git", "show", "main:" + SEEN], cwd=store_remote,
                       check=True, capture_output=True, text=True).stdout
    )
    assert set(published) == {"https://acme.example/one", "https://acme.example/two"}
    # The public repository is untouched by a private-store publish.
    assert git(public_remote, "rev-parse", "main") == public_head


def test_state_target_rejects_a_path_outside_the_allowlist(tmp_path):
    with pytest.raises(ValueError, match="allowlisted"):
        state.state_target(tmp_path, "database/../secrets.json")
    with pytest.raises(ValueError, match="allowlisted"):
        state.state_target(tmp_path, "config/settings.py")
