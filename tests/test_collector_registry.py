from __future__ import annotations

from collections import Counter

import pytest

from collector import ats_boards, bespoke, companies, company_watchlist, dou_rss, epam, generic, hirify
from collector.types import STATUS_FAILED, SourceResult

_NETWORK_MODULES = (ats_boards, companies, company_watchlist, generic, bespoke, dou_rss, epam, hirify)


class Offline(RuntimeError):
    pass


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every outbound call fail so we exercise each collector's error path."""

    def refuse(*_args, **_kwargs):
        raise Offline("network disabled in tests")

    for module in _NETWORK_MODULES:
        for name in (
            "fetch_text",
            "fetch_json",
            "fetch_text_allowing_bot_wall",
            "fetch_impersonated",
            "post_form_data",
            "post_json",
        ):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, refuse)
    monkeypatch.setattr(bespoke, "_fetch_zone3000_api_text", refuse)
    monkeypatch.setattr(bespoke, "_fetch_softserve_vacancies", refuse)
    monkeypatch.setattr(companies, "collect_telegram_channels", lambda: [])


def _stub_result(source_id: str, name: str) -> SourceResult:
    return SourceResult(
        source_id=source_id,
        source_name=name,
        source_url=None,
        jobs=[],
        status="healthy",
        error=None,
        response_ms=0,
        items_scanned=0,
    )


def test_registry_is_not_empty() -> None:
    assert len(companies._python_collectors()) >= 52


def test_every_dou_watchlist_company_has_a_registered_source() -> None:
    watchlist_slugs = {
        str(company["slug"])
        for company in companies.load_company_watchlist()
        if bool(company.get("enabled", True))
    }
    generic_slugs = {
        collector.__name__.removeprefix("collect_watchlist_").replace("_", "-")
        for collector in companies._watchlist_collectors()
    }

    enabled_bespoke_slugs = companies._BESPOKE_WATCHLIST_SLUGS & watchlist_slugs

    assert watchlist_slugs == enabled_bespoke_slugs | generic_slugs


def test_every_collector_degrades_gracefully_when_the_network_is_down(offline: None) -> None:
    for collector in companies._python_collectors():
        result = collector()

        assert isinstance(result, SourceResult), collector
        assert result.source_name, collector
        assert result.jobs == [], result.source_name
        assert result.items_scanned == 0, result.source_name
        assert result.response_ms >= 0, result.source_name
        assert result.status == STATUS_FAILED, result.source_name
        assert result.error, result.source_name


def test_source_ids_are_unique_across_the_registry(offline: None) -> None:
    ids = [collector().source_id for collector in companies._python_collectors()]
    duplicates = [source_id for source_id, count in Counter(ids).items() if count > 1]

    assert duplicates == []


def test_companies_registered_more_than_once_keep_one_display_name(offline: None) -> None:
    results = [collector() for collector in companies._python_collectors()]
    by_lowercase: dict[str, set[str]] = {}
    for result in results:
        by_lowercase.setdefault(result.source_name.lower(), set()).add(result.source_name)

    inconsistent = {key: names for key, names in by_lowercase.items() if len(names) > 1}

    assert inconsistent == {}


def test_registry_reads_aggregators_only_through_their_public_feeds() -> None:
    module_names = {collector.__module__ for collector in companies._python_collectors()}

    assert "collector.dou_rss" in module_names
    assert "collector.dou" not in module_names
    assert "collector.djinni" not in module_names


def test_disabled_bespoke_company_is_not_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        companies,
        "load_company_watchlist",
        lambda: [{"name": "EPAM", "slug": "epam-systems", "enabled": False}],
    )

    assert companies.collect_epam not in companies._python_collectors()


def test_collect_all_includes_optional_telegram_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        companies,
        "_python_collectors",
        lambda: [
            lambda: _stub_result("company:a@a.com", "A"),
            lambda: _stub_result("company:b@b.com", "B"),
        ],
    )
    monkeypatch.setattr(
        companies,
        "collect_telegram_channels",
        lambda: [_stub_result("telegram:chan", "Telegram @chan")],
    )

    result = companies.collect_all(max_workers=2)

    assert {source.source_id for source in result.source_results} == {
        "company:a@a.com",
        "company:b@b.com",
        "telegram:chan",
    }


def test_collect_all_isolates_collector_crashes(monkeypatch: pytest.MonkeyPatch) -> None:
    def crashing() -> SourceResult:
        raise Offline("collector blew up")

    monkeypatch.setattr(companies, "_python_collectors", lambda: [crashing])
    monkeypatch.setattr(companies, "collect_telegram_channels", lambda: [])

    result = companies.collect_all(max_workers=1)

    assert len(result.source_results) == 1
    assert result.source_results[0].status == STATUS_FAILED
    assert result.source_results[0].source_id == "collector-crash:crashing"
    assert result.source_results[0].error == "collector blew up"
