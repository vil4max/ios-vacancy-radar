from __future__ import annotations

import json
from pathlib import Path

import pytest

from collector import ats_boards

AI_DESCRIPTION = (
    "Build LLM-powered product features with RAG, embeddings and tool calling "
    "for our customers in a small product team."
)


def _serve(monkeypatch: pytest.MonkeyPatch, payloads: dict[str, object]) -> list[str]:
    calls: list[str] = []

    def fetch(url: str, **_kwargs):
        calls.append(url)
        return payloads[url]

    monkeypatch.setattr(ats_boards, "fetch_json", fetch)
    return calls


def test_greenhouse_unescapes_content_and_keeps_only_target_roles(monkeypatch) -> None:
    url = "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
    _serve(monkeypatch, {url: {"jobs": [
        {"id": 1, "title": "Senior iOS Engineer", "absolute_url": "https://jobs.acme.example/1",
         "location": {"name": "Kyiv, Ukraine"}, "content": "&lt;p&gt;Swift&lt;/p&gt;"},
        {"id": 2, "title": "Accountant", "absolute_url": "https://jobs.acme.example/2",
         "location": {"name": "Kyiv"}, "content": ""},
    ]}})

    jobs, scanned = ats_boards.collect_ats_board("Acme", {"ats": "greenhouse", "token": "acme"})

    assert scanned == 2
    assert jobs == [{
        "company": "Acme", "source": "company", "title": "Senior iOS Engineer",
        "url": "https://jobs.acme.example/1", "source_job_id": "1",
        "location": "Kyiv, Ukraine", "description": "<p>Swift</p>",
    }]


def test_unexpected_payload_fails_the_source(monkeypatch) -> None:
    _serve(monkeypatch, {"https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true": {"error": "nope"}})
    with pytest.raises(RuntimeError, match="Greenhouse API returned an unexpected payload"):
        ats_boards.collect_ats_board("Acme", {"ats": "greenhouse", "token": "acme"})


def test_board_map_skips_unknown_ats_without_losing_the_rest(tmp_path: Path, capsys) -> None:
    path = tmp_path / "boards.json"
    path.write_text(
        json.dumps({"boards": {
            "acme": {"ats": "taleo", "token": "acme"},
            "blank": {"ats": "lever", "token": ""},
            "usable": {"ats": "lever", "token": "usable"},
        }}),
        encoding="utf-8",
    )

    # An entry no collector supports must not take down the whole map: it is
    # loaded once per run, for every watchlist company.
    assert ats_boards.load_ats_boards(path) == {"usable": {"ats": "lever", "token": "usable"}}
    warnings = capsys.readouterr().err
    assert "acme" in warnings and "blank" in warnings


def test_workable_widget_maps_locations_and_remote(monkeypatch) -> None:
    url = "https://apply.workable.com/api/v1/widget/accounts/acme"
    _serve(monkeypatch, {url: {"jobs": [
        {"title": "Senior iOS Engineer", "url": "https://apply.workable.com/acme/j/IOS1/",
         "shortcode": "IOS1", "locations": [{"city": "Kyiv", "country": "Ukraine"}],
         "telecommuting": True},
        {"title": "Data Annotator", "shortcode": "DATA1"},
    ]}})

    jobs, scanned = ats_boards.collect_ats_board("Acme", {"ats": "workable", "token": "acme"})

    assert scanned == 2
    assert jobs == [{
        "company": "Acme", "source": "company", "title": "Senior iOS Engineer",
        "url": "https://apply.workable.com/acme/j/IOS1/", "source_job_id": "IOS1",
        "location": "Kyiv, Ukraine", "remote": "remote",
    }]


def test_discovery_only_probes_boards_that_have_a_collector() -> None:
    from scripts.discover_ats_boards import _PAGE_HINTS

    # A discovered board is meant to be pasted into the board map as it stands,
    # so discovery must not report an ATS this repository cannot collect.
    assert {ats for ats, _ in _PAGE_HINTS} <= ats_boards.SUPPORTED_ATS


def test_committed_board_map_targets_watchlist_slugs() -> None:
    from collector.company_watchlist import load_company_watchlist

    slugs = {company["slug"] for company in load_company_watchlist()}
    assert set(ats_boards.load_ats_boards()) <= slugs


def test_watchlist_company_with_board_uses_api_and_fresh_health_id(monkeypatch) -> None:
    from collector import company_watchlist

    monkeypatch.setattr(company_watchlist, "_ats_boards", lambda: {"acme": {"ats": "breezy", "token": "acme"}})
    monkeypatch.setattr(company_watchlist, "fetch_text", lambda *_a, **_k: pytest.fail("page scraped"))
    _serve(monkeypatch, {"https://acme.breezy.hr/json": [
        {"id": "b1", "name": "iOS Engineer", "url": "https://acme.breezy.hr/p/b1"},
    ]})

    result = company_watchlist.collect_watchlist_company(
        {"name": "Acme", "slug": "acme", "career_url": "https://acme.example/careers"}
    )

    assert result.status == "healthy"
    assert result.source_id == "company-ats:acme"
    assert result.items_scanned == 1
    assert [job["title"] for job in result.jobs] == ["iOS Engineer"]
