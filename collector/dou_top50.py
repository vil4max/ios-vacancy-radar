from __future__ import annotations

import csv
import io
import re
from typing import Any

from integrations.http_client import fetch_impersonated

TOP50_PAGE_URL = "https://jobs.dou.ua/top50/"
TOP50_ASSET_ROOT = "https://s.dou.ua/files/top50/"
_TOP50_CSV_PATTERN = re.compile(r"top50-[0-9_-]+(?:v\d+)?\.csv")
_TOP50_SCRIPT_PATTERN = re.compile(r'<script[^>]+src="(https://s\.dou\.ua/build/[^"]+\.js)"')


def discover_top50_csv_url(page_html: str) -> str:
    for script_url in _TOP50_SCRIPT_PATTERN.findall(page_html):
        script = fetch_impersonated(script_url)
        matches = _TOP50_CSV_PATTERN.findall(script)
        if matches:
            return TOP50_ASSET_ROOT + matches[-1]
    raise RuntimeError("DOU Top 50 CSV asset was not found")


def parse_top50_csv(csv_text: str) -> list[dict[str, Any]]:
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    periods = {str(row.get("date") or "") for row in rows}
    latest_period = max(periods, key=lambda value: tuple(reversed(value.split("-"))))
    companies: list[dict[str, Any]] = []
    for row in rows:
        if row.get("date") != latest_period:
            continue
        name = str(row.get("company") or "").strip()
        if not name:
            continue
        companies.append({"name": name, "top50_rank": int(row["rate"])})
    return sorted(companies, key=lambda company: int(company["top50_rank"]))


def fetch_top50() -> list[dict[str, Any]]:
    page_html = fetch_impersonated(TOP50_PAGE_URL)
    csv_url = discover_top50_csv_url(page_html)
    return parse_top50_csv(fetch_impersonated(csv_url))
