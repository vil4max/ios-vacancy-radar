from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from collector.career_discovery import resolve_career_url
from collector.dou_catalog import enrich_site_url, make_session

SERVICE_RATINGS_URL = "https://jobs.dou.ua/ratings/?type=service"
LARGE_SIZE_BANDS = frozenset({"1500+", "800-1500", "200-800"})


def default_service_ratings_path(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parents[1]
    return base / "database" / "dou_service_companies.json"


def default_career_overrides_path(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parents[1]
    return base / "database" / "company_career_overrides.json"


def default_manual_additions_path(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parents[1]
    return base / "database" / "company_manual_additions.json"


def load_career_overrides(path: Path | None = None) -> dict[str, str]:
    source = path or default_career_overrides_path()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("career overrides must be a JSON object")
    return {str(slug): str(url) for slug, url in payload.items() if url}


def load_manual_additions(path: Path | None = None) -> list[dict[str, str]]:
    payload = json.loads((path or default_manual_additions_path()).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("manual company additions must be a JSON list")
    return [company for company in payload if isinstance(company, dict)]


def parse_service_ratings(html: str) -> list[dict[str, Any]]:
    document = BeautifulSoup(html, "lxml")
    companies: list[dict[str, Any]] = []
    size_band: str | None = None
    size_label: str | None = None

    for row in document.select("tr"):
        heading = row.select_one("h3[id]")
        if heading is not None:
            raw_size_band = str(heading.get("id") or "").strip()
            size_band = raw_size_band.replace("—", "-").replace("–", "-") or None
            size_label = heading.get_text(" ", strip=True) or None
            continue
        if size_band not in LARGE_SIZE_BANDS:
            continue

        company_link = row.select_one("td.company-name a[href]")
        if company_link is None:
            continue
        href = str(company_link.get("href") or "").strip()
        slug_match = re.search(r"/companies/([^/]+)/poll/?", href)
        if not slug_match:
            continue
        name = company_link.get_text(" ", strip=True)
        if not name:
            continue

        score_node = row.select_one(".score.all")
        score_text = str(score_node.get("title") or score_node.get_text(strip=True)) if score_node else ""
        try:
            score = float(score_text)
        except ValueError:
            score = None

        count_node = row.select_one(".count")
        count_match = re.search(r"\d+", count_node.get_text(" ", strip=True) if count_node else "")
        scores = row.select("div.score")
        compensation_score = None
        if len(scores) > 1:
            try:
                compensation_score = float(scores[1].get_text(strip=True))
            except ValueError:
                pass
        companies.append(
            {
                "name": name,
                "slug": slug_match.group(1).lower(),
                "size_band": size_band,
                "size_label": size_label,
                "rating_score": score,
                "compensation_score": compensation_score,
                "survey_count": int(count_match.group(0)) if count_match else None,
                "dou_company_url": href.removesuffix("poll/").removesuffix("poll"),
                "enabled": True,
            }
        )

    return companies


def fetch_service_ratings() -> list[dict[str, Any]]:
    response = make_session().get(SERVICE_RATINGS_URL, timeout=30)
    response.raise_for_status()
    return parse_service_ratings(response.text)


def enrich_official_urls(
    companies: list[dict[str, Any]],
    *,
    overrides: dict[str, str] | None = None,
) -> tuple[int, int]:
    session = make_session()
    overrides = overrides if overrides is not None else load_career_overrides()
    sites_resolved = 0
    careers_resolved = 0
    for company in companies:
        slug = str(company.get("slug") or "").strip()
        if not slug:
            continue
        override_url = overrides.get(slug)
        try:
            company_site_url = enrich_site_url(slug, session)
        except requests.RequestException:
            company_site_url = None
        company["company_site_url"] = company_site_url
        if override_url:
            company["career_url"] = override_url
            company["career_url_source"] = "override"
            careers_resolved += 1
            if company_site_url:
                sites_resolved += 1
            continue
        if not company_site_url:
            company["career_url"] = None
            company["career_url_source"] = None
            continue
        sites_resolved += 1
        try:
            career_url = resolve_career_url(company_site_url, session)
        except requests.RequestException:
            career_url = None
        company["career_url"] = career_url
        company["career_url_source"] = "discovered" if career_url else None
        if company["career_url"]:
            careers_resolved += 1
    return sites_resolved, careers_resolved


def merge_top50_companies(
    companies: list[dict[str, Any]],
    top50: list[dict[str, Any]],
    *,
    career_urls: dict[str, str],
) -> int:
    known_names = {str(company.get("name") or "").strip().lower() for company in companies}
    aliases = {
        "epam ukraine": "epam",
        "globallogic ukraine": "globallogic",
        "grid dynamics group": "grid dynamics",
    }
    known_names |= {alias for name in known_names for alias, target in aliases.items() if target == name}
    added = 0
    for candidate in top50:
        name = str(candidate.get("name") or "").strip()
        normalized_name = name.lower()
        if normalized_name in known_names or aliases.get(normalized_name) in known_names:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", normalized_name).strip("-")
        career_url = career_urls.get(slug)
        if not career_url:
            continue
        companies.append(
            {
                "name": name,
                "slug": slug,
                "rating_score": None,
                "compensation_score": None,
                "survey_count": None,
                "dou_company_url": None,
                "company_site_url": None,
                "career_url": career_url,
                "career_url_source": "override",
                "enabled": True,
            }
        )
        known_names.add(normalized_name)
        added += 1
    return added


def merge_manual_companies(
    companies: list[dict[str, Any]],
    manual_companies: list[dict[str, str]],
) -> int:
    known_slugs = {str(company.get("slug") or "") for company in companies}
    added = 0
    for manual in manual_companies:
        slug = str(manual.get("slug") or "").strip()
        name = str(manual.get("name") or "").strip()
        career_url = str(manual.get("career_url") or "").strip()
        if not slug or not name or not career_url or slug in known_slugs:
            continue
        companies.append(
            {
                "name": name,
                "slug": slug,
                "rating_score": None,
                "compensation_score": None,
                "survey_count": None,
                "dou_company_url": None,
                "company_site_url": None,
                "career_url": career_url,
                "career_url_source": "manual",
                "enabled": True,
            }
        )
        known_slugs.add(slug)
        added += 1
    return added


def preserve_watchlist_state(
    companies: list[dict[str, Any]],
    existing_companies: list[dict[str, Any]],
) -> None:
    existing_by_slug = {
        str(company.get("slug") or ""): company
        for company in existing_companies
    }
    for company in companies:
        slug = str(company.get("slug") or "")
        existing = existing_by_slug.get(slug) or {}
        company["enabled"] = bool(existing.get("enabled", company.get("enabled", True)))
        for field in ("company_site_url", "career_url", "career_url_source"):
            if not company.get(field) and existing.get(field):
                company[field] = existing[field]


def save_service_ratings(path: Path, companies: list[dict[str, Any]]) -> None:
    payload = {
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": SERVICE_RATINGS_URL,
        "scope": "service companies with 200+ specialists",
        "companies": companies,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
