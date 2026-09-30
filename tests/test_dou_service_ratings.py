from __future__ import annotations

import json
from pathlib import Path

from collector.dou_service_ratings import (
    enrich_official_urls,
    merge_top50_companies,
    merge_manual_companies,
    parse_service_ratings,
    preserve_watchlist_state,
    save_service_ratings,
)


_HTML = """
<table>
  <tr><td colspan="18"><h3 id="1500+">понад 1500 спеціалістів</h3></td></tr>
  <tr>
    <td class="company-name"><a href="https://jobs.dou.ua/companies/n-ix/poll/">N-iX</a></td>
                    <td><div class="score all" title="89.04">89.0</div><span class="count">184</span></td>
                    <td><div class="score">79.8</div></td>
  </tr>
  <tr><td colspan="18"><h3 id="200—800">200...800 спеціалістів</h3></td></tr>
  <tr class="no-cat">
    <td class="company-name"><a href="https://jobs.dou.ua/companies/agileengine/poll/">AgileEngine</a></td>
    <td><div class="score all">90.3</div><span class="count">48 анкет</span></td>
  </tr>
  <tr><td colspan="18"><h3 id="81-200">81...200 спеціалістів</h3></td></tr>
  <tr>
    <td class="company-name"><a href="https://jobs.dou.ua/companies/small/poll/">Small</a></td>
    <td><div class="score all">100.0</div><span class="count">40</span></td>
  </tr>
</table>
"""


def test_parse_service_ratings_keeps_service_companies_with_200_plus_specialists() -> None:
    companies = parse_service_ratings(_HTML)

    assert [company["name"] for company in companies] == ["N-iX", "AgileEngine"]
    assert companies[0]["size_band"] == "1500+"
    assert companies[0]["rating_score"] == 89.04
    assert companies[0]["compensation_score"] == 79.8
    assert companies[0]["survey_count"] == 184
    assert companies[0]["enabled"] is True
    assert companies[0]["dou_company_url"] == "https://jobs.dou.ua/companies/n-ix/"
    assert companies[1]["size_band"] == "200-800"


def test_save_service_ratings_writes_research_metadata(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.json"
    companies = parse_service_ratings(_HTML)

    save_service_ratings(path, companies)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["source"] == "https://jobs.dou.ua/ratings/?type=service"
    assert payload["scope"] == "service companies with 200+ specialists"
    assert payload["companies"] == companies


def test_override_resolves_company_without_a_dou_site(monkeypatch) -> None:
    monkeypatch.setattr("collector.dou_service_ratings.make_session", lambda: object())
    monkeypatch.setattr("collector.dou_service_ratings.enrich_site_url", lambda *_args: None)
    companies = [{"name": "Develux", "slug": "develux"}]

    sites, careers = enrich_official_urls(
        companies,
        overrides={"develux": "https://develux.peopleforce.io/careers"},
    )

    assert (sites, careers) == (0, 1)
    assert companies[0]["career_url"] == "https://develux.peopleforce.io/careers"
    assert companies[0]["career_url_source"] == "override"


def test_merge_top50_adds_only_companies_with_verified_career_urls() -> None:
    companies = [{"name": "EPAM", "slug": "epam-systems"}]
    top50 = [
        {"name": "EPAM Ukraine", "top50_rank": 1},
        {"name": "Ajax Systems", "top50_rank": 3},
        {"name": "Unknown", "top50_rank": 50},
    ]

    added = merge_top50_companies(
        companies,
        top50,
        career_urls={"ajax-systems": "https://jobs.lever.co/ajax"},
    )

    assert added == 1
    assert [company["name"] for company in companies] == ["EPAM", "Ajax Systems"]
    assert companies[1]["rating_score"] is None
    assert companies[1]["enabled"] is True


def test_merge_manual_companies_adds_official_career_source_once() -> None:
    companies = [{"name": "Existing", "slug": "existing"}]
    manual = [
        {"name": "Existing", "slug": "existing", "career_url": "https://existing.test/jobs"},
        {"name": "Extra", "slug": "extra", "career_url": "https://extra.test/careers"},
    ]

    added = merge_manual_companies(companies, manual)

    assert added == 1
    assert companies[1]["name"] == "Extra"
    assert companies[1]["career_url_source"] == "manual"


def test_preserve_watchlist_state_keeps_manual_values() -> None:
    companies = [
        {"slug": "keep", "enabled": True},
        {"slug": "exclude", "enabled": True},
        {"slug": "new", "enabled": True},
    ]

    preserve_watchlist_state(
        companies,
        [
            {"slug": "keep", "enabled": True},
            {
                "slug": "exclude",
                "enabled": False,
                "career_url": "https://example.test/careers",
                "career_url_source": "override",
            },
        ],
    )

    assert [company["enabled"] for company in companies] == [True, False, True]
    assert companies[1]["career_url"] == "https://example.test/careers"
    assert companies[1]["career_url_source"] == "override"
