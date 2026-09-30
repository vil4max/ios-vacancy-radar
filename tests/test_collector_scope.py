from pathlib import Path

import pytest

from scripts import run_pipeline


def test_required_telegram_delivery_fails_before_collection(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", ["run_pipeline.py"])
    monkeypatch.setenv("REQUIRE_TELEGRAM_DELIVERY", "1")
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("SEED_SEEN_ONLY", raising=False)
    monkeypatch.setenv("COLLECT_DIAGNOSTICS_PATH", str(tmp_path / "diagnostics.json"))
    monkeypatch.setattr(run_pipeline, "collect_vacancies", lambda: pytest.fail("Must fail before collection"))
    assert run_pipeline.main() == 1


def test_personal_career_modules_and_mail_workflows_are_absent():
    root = Path(__file__).resolve().parents[1]
    for path in (
        "analytics", "planner/plan.py", "integrations/email_imap.py",
        "integrations/email_smtp.py", "integrations/mail_classify.py",
        "project_sync",
        ".github/workflows/imap-poll.yml", ".github/workflows/daily-email-report.yml",
    ):
        assert not (root / path).exists(), path
