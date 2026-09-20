from __future__ import annotations

import json

import pytest

from storage.seen import mark_seen
from reporter.collector_health import safe_error
from scripts import run_pipeline
from tests.conftest import make_vacancy


def test_next_city_variant_is_not_new():
    first = make_vacancy(url="https://example.com/kyiv")
    other = make_vacancy(url="https://example.com/remote")
    seen = {}
    mark_seen(seen, first)
    assert run_pipeline.select_fresh([other], seen, seen_gate=True) == []


def test_diagnostics_redact_credentials_and_urls(monkeypatch):
    monkeypatch.setenv("CAREER_AGENT_TOKEN", "private-secret")
    assert safe_error("bad private-secret at https://user:password@site.test/?token=other") == "bad [redacted] at [url]"


@pytest.mark.parametrize("notify_ok,outage", [(False, False), (True, True)])
def test_main_fails_on_delivery_error_or_total_outage_and_preserves_partial_history(monkeypatch, tmp_path, notify_ok, outage):
    monkeypatch.setattr("sys.argv", ["run_pipeline.py"])
    seen_path = tmp_path / "seen.json"
    report_path = tmp_path / "report.json"
    cursor_path = tmp_path / "cursors.json"
    monkeypatch.setenv("SEEN_PATH", str(seen_path))
    monkeypatch.setenv("COLLECT_DIAGNOSTICS_PATH", str(report_path))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    monkeypatch.setattr(run_pipeline, "default_telegram_cursors_path", lambda root: cursor_path)
    monkeypatch.setattr(run_pipeline, "collect_vacancies", lambda: ([], 0, (), {"company_outage": outage, "telegram_cursor_updates": {"chan": 99}}, frozenset()))
    def process(vacancies, seen, **kwargs):
        mark_seen(seen, make_vacancy())
        return 0, 1, notify_ok
    monkeypatch.setattr(run_pipeline, "process_new_vacancies", process)
    assert run_pipeline.main() == 1
    assert "https://example.com/job/1" in json.loads(seen_path.read_text())
    assert json.loads(report_path.read_text())["status"] == "failed"
    if not notify_ok:
        assert not cursor_path.exists()
