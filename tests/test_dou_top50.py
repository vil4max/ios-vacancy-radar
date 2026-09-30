from __future__ import annotations

from collector.dou_top50 import discover_top50_csv_url, parse_top50_csv


def test_discover_top50_csv_url_reads_current_asset(monkeypatch) -> None:
    page = '<script src="https://s.dou.ua/build/current.js"></script>'
    monkeypatch.setattr(
        "collector.dou_top50.fetch_impersonated",
        lambda _url: 'd3.csv(`${PATH}top50-2026-08_v3.csv`)',
    )

    assert discover_top50_csv_url(page) == (
        "https://s.dou.ua/files/top50/top50-2026-08_v3.csv"
    )


def test_parse_top50_csv_keeps_latest_period() -> None:
    csv_text = """date,rate,company,isDouData,cities,staffTotal,staffTech,openPositions
01-2026,1,Old Company,,,1000,900,
07-2026,2,New Company,,,900,800,
07-2026,1,Leader,,,1200,1000,
"""

    companies = parse_top50_csv(csv_text)

    assert companies == [
        {"name": "Leader", "top50_rank": 1},
        {"name": "New Company", "top50_rank": 2},
    ]
