from __future__ import annotations

import pytest

from collector import hirify
from parser.normalize import normalize_many

AI_DESCRIPTION = "Build LLM-powered agent workflows with RAG and structured outputs for our product."


def _page(items: list[dict], *, page: int = 1, last_page: int = 1) -> dict:
    return {"current_page": page, "last_page": last_page, "data": items}


def _serve(monkeypatch: pytest.MonkeyPatch, pages: list[dict]) -> list[str]:
    calls: list[str] = []

    def fetch(url: str, **_kwargs):
        calls.append(url)
        return pages[len(calls) - 1]

    monkeypatch.setattr(hirify, "fetch_json", fetch)
    return calls


def test_collect_hirify_maps_fields_and_builds_the_job_url(monkeypatch) -> None:
    _serve(monkeypatch, [_page([
        {"id": 787387, "title": "Senior iOS Engineer", "slug": "787387-senior-ios-engineer",
         "company_title": "ArtWorkout", "work_format": ["remote"], "office_locations": [],
         "tldr": "Own the graphics pipeline.", "tags": [{"name": "swift"}, {"name": "metal"}]},
    ])])

    result = hirify.collect_hirify()

    assert result.status == "healthy"
    assert result.items_scanned == 1
    assert result.jobs == [{
        "company": "ArtWorkout", "title": "Senior iOS Engineer",
        "url": "https://hirify.me/jobs/787387-senior-ios-engineer",
        "source": "hirify.me", "source_job_id": "hirify:787387",
        "location": None, "remote": "remote",
        "description": "Own the graphics pipeline.\nStack: swift, metal",
        "russian_company": False,
    }]


def test_collect_hirify_falls_back_to_hirify_for_confidential_postings(monkeypatch) -> None:
    _serve(monkeypatch, [_page([
        {"id": 1, "title": "Senior iOS Developer", "slug": "1-senior-ios-developer",
         "company_title": "%hirify_global%", "work_format": ["remote"]},
        {"id": 2, "title": "Senior iOS Developer", "slug": "2-senior-ios-developer",
         "company_title": None, "work_format": ["remote"]},
    ])])

    result = hirify.collect_hirify()

    assert [job["company"] for job in result.jobs] == ["Hirify", "Hirify"]


def test_collect_hirify_skips_archived_scam_and_off_target_titles(monkeypatch) -> None:
    _serve(monkeypatch, [_page([
        {"id": 1, "title": "Senior iOS Developer", "slug": "1-x", "is_archived": True},
        {"id": 2, "title": "Senior iOS Developer", "slug": "2-x", "is_scam": True},
        {"id": 3, "title": "Senior iOS Developer", "slug": "3-x", "is_potential_scam": True},
        {"id": 4, "title": "Senior Android Developer", "slug": "4-x"},
        {"id": 5, "title": "Senior iOS Developer", "slug": "5-x", "company_title": "Acme"},
    ])])

    result = hirify.collect_hirify()

    assert [job["source_job_id"] for job in result.jobs] == ["hirify:5"]


def test_collect_hirify_maps_location_and_remote_mode(monkeypatch) -> None:
    _serve(monkeypatch, [_page([
        {"id": 1, "title": "iOS Developer", "slug": "1-x", "company_title": "Acme",
         "work_format": ["hybrid"], "office_locations": ["united_states", "switzerland"]},
    ])])

    result = hirify.collect_hirify()

    job = result.jobs[0]
    assert job["remote"] == "hybrid"
    assert job["location"] == "United States / Switzerland"


def test_collect_hirify_marks_only_the_russian_companies_board(monkeypatch) -> None:
    _serve(monkeypatch, [_page([
        {"id": 1, "title": "iOS Developer", "slug": "1-a", "company_title": "Acme", "source_secondary": "ru"},
        {"id": 2, "title": "iOS Developer", "slug": "2-b", "company_title": "Beta", "source_secondary": "ru-global"},
        {"id": 3, "title": "iOS Developer", "slug": "3-c", "company_title": "Gamma", "source_secondary": "global"},
    ])])

    result = hirify.collect_hirify()

    assert [job["russian_company"] for job in result.jobs] == [True, False, False]
    assert [vacancy.russian_company for vacancy in normalize_many(result.jobs)] == [True, False, False]


def test_collect_hirify_paginates_until_last_page(monkeypatch) -> None:
    calls = _serve(monkeypatch, [
        _page([{"id": 1, "title": "Senior iOS Developer", "slug": "1-x", "company_title": "Acme"}],
              page=1, last_page=2),
        _page([{"id": 2, "title": "Senior iOS Developer", "slug": "2-x", "company_title": "Acme"}],
              page=2, last_page=2),
    ])

    result = hirify.collect_hirify()

    assert len(calls) == 2
    assert "page=1" in calls[0] and "page=2" in calls[1]
    assert result.items_scanned == 2
    assert [job["source_job_id"] for job in result.jobs] == ["hirify:1", "hirify:2"]


def test_collect_hirify_fails_cleanly_on_bad_payload(monkeypatch) -> None:
    monkeypatch.setattr(hirify, "fetch_json", lambda *_a, **_k: {"data": "not-a-list"})

    result = hirify.collect_hirify()

    assert result.status == "failed"
    assert "missing data" in result.error


def test_collect_hirify_is_registered_in_the_pipeline() -> None:
    from collector.companies import _python_collectors

    names = {collector.__name__ for collector in _python_collectors()}
    assert "collect_hirify" in names
