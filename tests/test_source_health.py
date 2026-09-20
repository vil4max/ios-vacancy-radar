from __future__ import annotations

from pathlib import Path

from collector.results import source_failed, source_id_for, source_ok
from collector.types import SourceResult
from storage.source_health import (
    best_scanned,
    classify_degraded,
    current_search_policy,
    default_baseline_path,
    empty_runs,
    load_baseline,
    save_baseline,
    update_baseline,
)


def _result(source_id: str, *, scanned: int, status: str = "healthy", name: str = "Acme") -> SourceResult:
    return SourceResult(
        source_id=source_id,
        source_name=name,
        source_url="https://acme.com",
        jobs=[],
        status=status,
        error=None,
        response_ms=1,
        items_scanned=scanned,
    )


def test_source_id_includes_host_so_duplicate_companies_stay_separate() -> None:
    lever = source_id_for("ELEKS", "https://api.lever.co/v0/postings/eleks")
    site = source_id_for("ELEKS", "https://careers.eleks.com/vacancies/")

    assert lever != site
    assert lever == "company:eleks@api.lever.co"
    assert site == "company:eleks@careers.eleks.com"


def test_source_id_strips_www_and_tolerates_missing_url() -> None:
    assert source_id_for("Acme", "https://www.acme.com/jobs") == "company:acme@acme.com"
    assert source_id_for("Acme") == "company:acme"


def test_source_ok_defaults_scanned_to_job_count() -> None:
    result = source_ok("Acme", "https://acme.com", [{"url": "1"}, {"url": "2"}], 0.0)

    assert result.items_scanned == 2
    assert result.status == "healthy"
    assert result.is_usable is True


def test_source_failed_is_not_usable() -> None:
    result = source_failed("Acme", "https://acme.com", ValueError("bad"), 0.0)

    assert result.status == "failed"
    assert result.is_usable is False
    assert result.error == "bad"


def test_default_baseline_path_sits_next_to_seen_store(tmp_path: Path) -> None:
    assert default_baseline_path(tmp_path) == tmp_path / "database" / "source_baseline.json"


def test_load_baseline_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert load_baseline(tmp_path / "nope.json") == {}


def test_load_baseline_ignores_broken_or_unexpected_content(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_baseline(broken) == {}

    wrong_shape = tmp_path / "list.json"
    wrong_shape.write_text('["a"]', encoding="utf-8")
    assert load_baseline(wrong_shape) == {}

    mixed = tmp_path / "mixed.json"
    mixed.write_text('{"a": {"best_scanned": 3}, "b": 5}', encoding="utf-8")
    assert load_baseline(mixed) == {"a": {"best_scanned": 3}}


def test_save_and_load_baseline_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "baseline.json"
    save_baseline(path, {"b": {"best_scanned": 2}, "a": {"best_scanned": 1}})

    assert path.read_text(encoding="utf-8").index('"a"') < path.read_text(encoding="utf-8").index('"b"')
    assert load_baseline(path) == {"a": {"best_scanned": 1}, "b": {"best_scanned": 2}}


def test_best_scanned_tolerates_missing_and_invalid_values() -> None:
    policy = current_search_policy()
    baseline = {"a": {"best_scanned": "12", "search_policy": policy}, "b": {"best_scanned": "many", "search_policy": policy}, "c": {}}

    assert best_scanned(baseline, "a") == 12
    assert best_scanned(baseline, "b") == 0
    assert best_scanned(baseline, "c") == 0
    assert best_scanned(baseline, "missing") == 0


def test_empty_runs_tolerates_missing_and_invalid_values() -> None:
    baseline = {"a": {"empty_runs": "2"}, "b": {"empty_runs": "many"}, "c": {}}

    assert empty_runs(baseline, "a") == 2
    assert empty_runs(baseline, "b") == 0
    assert empty_runs(baseline, "c") == 0
    assert empty_runs(baseline, "missing") == 0


def test_classify_degraded_flags_source_that_stopped_parsing() -> None:
    results = [_result("company:acme@acme.com", scanned=0, name="Acme")]
    baseline = {"company:acme@acme.com": {"best_scanned": 40, "search_policy": current_search_policy()}}

    degraded = classify_degraded(results, baseline)

    assert degraded == ["Acme"]
    assert results[0].status == "degraded"
    assert "parsed 0 items" in (results[0].error or "")


def test_classify_degraded_leaves_new_sources_alone() -> None:
    results = [_result("company:new@new.com", scanned=0)]

    assert classify_degraded(results, {}) == []
    assert results[0].status == "healthy"


def test_classify_degraded_accepts_authoritative_empty_source() -> None:
    result = _result("company:empty@empty.com", scanned=0, name="Empty")
    result.empty_is_healthy = True

    assert classify_degraded([result], {result.source_id: {"best_scanned": 20}}) == []
    assert result.status == "healthy"


def test_classify_degraded_flags_third_consecutive_empty_run() -> None:
    results = [_result("company:new@new.com", scanned=0, name="New")]
    baseline = {"company:new@new.com": {"best_scanned": 0, "empty_runs": 2}}

    degraded = classify_degraded(results, baseline)

    assert degraded == ["New"]
    assert results[0].status == "degraded"
    assert "3 runs" in (results[0].error or "")


def test_classify_degraded_flags_steep_drop_from_high_water_mark() -> None:
    results = [_result("company:acme@acme.com", scanned=3, name="Acme")]
    baseline = {"company:acme@acme.com": {"best_scanned": 20, "search_policy": current_search_policy()}}

    degraded = classify_degraded(results, baseline)

    assert degraded == ["Acme"]
    assert results[0].status == "degraded"
    assert "parsed 3 items" in (results[0].error or "")


def test_classify_degraded_ignores_small_drops() -> None:
    results = [_result("company:acme@acme.com", scanned=110)]
    baseline = {"company:acme@acme.com": {"best_scanned": 127}}

    assert classify_degraded(results, baseline) == []
    assert results[0].status == "healthy"


def test_classify_degraded_leaves_working_and_failed_sources_alone() -> None:
    working = _result("company:a@a.com", scanned=5)
    broken = _result("company:b@b.com", scanned=0, status="failed")
    baseline = {"company:a@a.com": {"best_scanned": 5}, "company:b@b.com": {"best_scanned": 5}}

    assert classify_degraded([working, broken], baseline) == []
    assert working.status == "healthy"
    assert broken.status == "failed"


def test_update_baseline_keeps_the_high_water_mark() -> None:
    baseline = {"company:a@a.com": {"best_scanned": 40, "search_policy": current_search_policy(), "last_nonzero": "2026-01-01T00:00:00+00:00"}}
    results = [_result("company:a@a.com", scanned=12)]

    updated = update_baseline(baseline, results, now="2026-07-27T10:00:00+00:00")

    assert updated["company:a@a.com"]["best_scanned"] == 40
    assert updated["company:a@a.com"]["last_scanned"] == 12
    assert updated["company:a@a.com"]["last_nonzero"] == "2026-07-27T10:00:00+00:00"
    assert updated["company:a@a.com"]["last_success_at"] == "2026-07-27T10:00:00+00:00"
    assert updated["company:a@a.com"]["empty_runs"] == 0


def test_update_baseline_records_new_high_and_skips_failed_sources() -> None:
    results = [
        _result("company:a@a.com", scanned=99, name="A"),
        _result("company:b@b.com", scanned=0, status="failed", name="B"),
    ]

    updated = update_baseline({}, results, now="2026-07-27T10:00:00+00:00")

    assert updated["company:a@a.com"] == {
        "name": "A",
        "search_policy": current_search_policy(),
        "best_scanned": 99,
        "last_scanned": 99,
        "last_success_at": "2026-07-27T10:00:00+00:00",
        "empty_runs": 0,
        "last_nonzero": "2026-07-27T10:00:00+00:00",
    }
    assert "company:b@b.com" not in updated


def test_update_baseline_does_not_stamp_last_nonzero_for_empty_runs() -> None:
    updated = update_baseline(
        {"company:a@a.com": {"empty_runs": 1}},
        [_result("company:a@a.com", scanned=0)],
        now="2026-07-27T10:00:00+00:00",
    )

    assert "last_nonzero" not in updated["company:a@a.com"]
    assert updated["company:a@a.com"]["last_success_at"] == "2026-07-27T10:00:00+00:00"
    assert updated["company:a@a.com"]["empty_runs"] == 2


def test_update_baseline_generates_timestamp_when_not_given() -> None:
    updated = update_baseline({}, [_result("company:a@a.com", scanned=1)])

    assert updated["company:a@a.com"]["last_nonzero"].endswith("+00:00")


def test_search_policy_change_resets_the_high_water_mark() -> None:
    # Legacy records were collected with iOS and AI queries ("ios+ai"); the
    # search is now iOS-only, so an old high-water mark cannot prove breakage.
    results = [_result("company:acme@acme.com", scanned=1, name="Acme")]
    baseline = {"company:acme@acme.com": {"best_scanned": 150}}

    assert classify_degraded(results, baseline) == []
    updated = update_baseline(baseline, results, now="2026-09-15T10:00:00+00:00")
    assert updated["company:acme@acme.com"]["best_scanned"] == 1
    assert updated["company:acme@acme.com"]["search_policy"] == "ios"
