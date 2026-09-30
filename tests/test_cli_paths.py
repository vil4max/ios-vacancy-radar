import pytest

from config.paths import workspace_path
from scripts import discover_dou_companies, evaluate_search_quality
from scripts import refresh_dou_service_watchlist, runtime_state


def test_paths_resolve_inside_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert workspace_path("nested/../result.json") == tmp_path.resolve() / "result.json"
    assert workspace_path(tmp_path / "nested/result.json") == tmp_path.resolve() / "nested/result.json"


@pytest.mark.parametrize("escape", ["../outside.json", "../workspace-other/file.json"])
def test_traversal_and_sibling_prefix_are_rejected(tmp_path, monkeypatch, escape):
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.chdir(root)
    with pytest.raises(ValueError, match="working directory"):
        workspace_path(escape)


def test_symlink_target_must_stay_in_workspace(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    monkeypatch.chdir(root)
    with pytest.raises(ValueError, match="working directory"):
        workspace_path("escape/new/file.json")


@pytest.mark.parametrize("module,option", [
    (discover_dou_companies, "--seed-path"),
    (refresh_dou_service_watchlist, "--output"),
    (evaluate_search_quality, "--dataset"),
])
def test_cli_rejects_external_path_before_io(tmp_path, monkeypatch, module, option):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", [module.__name__, option, "../outside.json"])

    def unexpected(*args, **kwargs):
        pytest.fail("Untrusted path reached network, credentials or file access")

    for name in ("make_session", "fetch_service_ratings", "load_seen", "evaluate"):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, unexpected)
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2


def test_runtime_snapshot_rejected_before_git(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["runtime_state", "refresh", "database/seen.json", "--snapshot", "../outside.json"])
    monkeypatch.setattr(runtime_state, "fetch", lambda *_: pytest.fail("Unsafe path reached Git"))
    assert runtime_state.main() == 1
    assert not (tmp_path.parent / "outside.json").exists()


def test_runtime_symlink_batch_rejected_before_any_write(tmp_path, monkeypatch):
    (tmp_path / "database").mkdir()
    (tmp_path / "diagnostics").mkdir()
    first = tmp_path / "database/seen.json"
    first.write_text("original")
    (tmp_path / "database/source_baseline.json").symlink_to(tmp_path.parent / "outside.json")
    monkeypatch.setattr(runtime_state, "fetch", lambda *_: "revision")
    with pytest.raises(ValueError):
        runtime_state.refresh(tmp_path, ["database/seen.json", "database/source_baseline.json"], tmp_path / "diagnostics/snapshot.json")
    assert first.read_text() == "original"


def test_runtime_diagnostic_symlink_does_not_escape(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "diagnostics").symlink_to(outside, target_is_directory=True)
    monkeypatch.chdir(root)
    monkeypatch.setattr("sys.argv", ["runtime_state", "refresh", "database/seen.json"])
    assert runtime_state.main() == 1
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("invalid_snapshot", [
    "scripts/runtime_state.py",
    "database/seen.json",
    "snapshot.json",
    "diagnostics/../escape.json",
    "diagnostics/nested/file.json",
    "diagnostics/not_json.txt",
])
def test_runtime_snapshot_rejects_non_diagnostics_and_traversal(tmp_path, monkeypatch, invalid_snapshot):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "diagnostics").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("sys.argv", ["runtime_state", "refresh", "database/seen.json", "--snapshot", invalid_snapshot])
    monkeypatch.setattr(runtime_state, "fetch", lambda *_: pytest.fail("Unsafe path reached Git"))
    assert runtime_state.main() == 1
