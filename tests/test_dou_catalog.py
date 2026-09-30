from __future__ import annotations

from pathlib import Path

import pytest

from collector import dou_catalog
from collector.dou_catalog import (
    companies_for_collect,
    merge_seed,
    parse_companies_index,
)


INDEX_HTML = """
<li class="l-company"><div class="company">
  <div class="h2">
    <a class="cn-a" href="https://jobs.dou.ua/companies/evoplay/">EVOPLAY</a>
  </div>
  <div class="site">
    <a href="https://jobs.dou.ua/companies/evoplay/vacancies/"><span>Вакансії</span> 38</a>
  </div>
</div></li>
<li class="l-company"><div class="company">
  <div class="h2">
    <a class="cn-a" href="https://jobs.dou.ua/companies/creatio/">Creatio</a>
  </div>
  <div class="site">
    <a href="https://jobs.dou.ua/companies/creatio/vacancies/"><span>Вакансії</span> 0</a>
  </div>
</div></li>
"""

PROFILE_HTML = """
<div class="site">
  <a href="https://example.com/careers/" target="_blank" rel="nofollow">Сайт</a>
</div>
"""


def test_parse_companies_index_reads_slug_name_and_vacancy_count() -> None:
    rows = parse_companies_index(INDEX_HTML)
    assert [(row["slug"], row["name"], row["vacancy_count"]) for row in rows] == [
        ("evoplay", "EVOPLAY", 38),
        ("creatio", "Creatio", 0),
    ]
    assert rows[0]["vacancies_url"] == "https://jobs.dou.ua/companies/evoplay/vacancies/"


def test_merge_seed_upserts_by_slug_and_keeps_existing_site() -> None:
    old = {
        "updated_at": None,
        "source": "https://jobs.dou.ua/companies/",
        "companies": [
            {
                "name": "Old Evoplay",
                "slug": "evoplay",
                "site_url": "https://kept.example/",
                "vacancies_url": "https://jobs.dou.ua/companies/evoplay/vacancies/",
                "vacancy_count": 10,
            }
        ],
    }
    seed, stats = merge_seed(
        old,
        [
            {
                "name": "EVOPLAY",
                "slug": "evoplay",
                "site_url": None,
                "vacancies_url": "https://jobs.dou.ua/companies/evoplay/vacancies/",
                "vacancy_count": 38,
            },
            {
                "name": "Creatio",
                "slug": "creatio",
                "site_url": None,
                "vacancies_url": "https://jobs.dou.ua/companies/creatio/vacancies/",
                "vacancy_count": 2,
            },
        ],
    )
    assert stats["added"] == 1
    assert stats["updated"] == 1
    by_slug = {row["slug"]: row for row in seed["companies"]}
    assert by_slug["evoplay"]["site_url"] == "https://kept.example/"
    assert by_slug["evoplay"]["vacancy_count"] == 38
    assert by_slug["evoplay"]["name"] == "EVOPLAY"
    assert by_slug["creatio"]["name"] == "Creatio"


def test_companies_for_collect_skips_zero_vacancies_and_dedupes_slugs() -> None:
    seed = {
        "companies": [
            {"name": "Manual", "slug": "manual-co"},
            {"name": "Hot", "slug": "hot", "vacancy_count": 5},
            {"name": "Cold", "slug": "cold", "vacancy_count": 0},
            {"name": "Skip Me", "slug": "skip-me", "vacancy_count": 9},
        ]
    }
    rows = companies_for_collect(seed, skip_slugs={"skip-me"}, feed_limit=10)
    assert [(row["slug"], row["name"]) for row in rows] == [
        ("manual-co", "Manual"),
        ("hot", "Hot"),
    ]


def test_companies_for_collect_respects_feed_limit_by_vacancy_count() -> None:
    seed = {
        "companies": [
            {"name": "A", "slug": "a", "vacancy_count": 1},
            {"name": "B", "slug": "b", "vacancy_count": 9},
            {"name": "C", "slug": "c", "vacancy_count": 3},
        ]
    }
    rows = companies_for_collect(seed, feed_limit=2)
    assert [row["slug"] for row in rows] == ["b", "c"]


def test_enrich_site_url_uses_profile_html(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        text = PROFILE_HTML

        def raise_for_status(self) -> None:
            return None

    class FakeSession:
        def get(self, url: str, timeout: int = 30):
            assert url.endswith("/companies/evoplay/")
            return FakeResponse()

    assert dou_catalog.enrich_site_url("evoplay", FakeSession()) == "https://example.com/careers/"


def test_load_and_save_seed_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "dou_companies.json"
    seed = {
        "updated_at": "2026-07-28T00:00:00+00:00",
        "source": "https://jobs.dou.ua/companies/",
        "companies": [
            {
                "name": "Creatio",
                "slug": "creatio",
                "site_url": None,
                "vacancies_url": "https://jobs.dou.ua/companies/creatio/vacancies/",
            }
        ],
    }
    dou_catalog.save_seed(path, seed)
    loaded = dou_catalog.load_seed(path)
    assert loaded["companies"][0]["slug"] == "creatio"
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_missing_seed_file_returns_empty(tmp_path: Path) -> None:
    assert dou_catalog.load_seed(tmp_path / "missing.json")["companies"] == []
