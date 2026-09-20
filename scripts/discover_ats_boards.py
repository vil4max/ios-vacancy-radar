#!/usr/bin/env python3
"""Find public ATS job-board APIs behind watchlist career pages.

Discovery only: it prints candidates for owner review and never edits the
watchlist. Public ATS APIs are published for job syndication, so they remain
reachable when a marketing site rejects datacenter traffic.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.company_watchlist import load_company_watchlist  # noqa: E402
from integrations.http_client import fetch_json, fetch_text_allowing_bot_wall  # noqa: E402
from parser.normalize import is_ios_job  # noqa: E402

_TIMEOUT = 15
_TOKEN = r"([A-Za-z0-9][A-Za-z0-9_-]{1,60})"
# Board tokens embedded in career pages are stronger evidence than slug guesses.
# Only an ATS listed in ats_boards.SUPPORTED_ATS belongs here, so every reported
# board can be added to database/company_ats_boards.json as it stands.
_PAGE_HINTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("greenhouse", re.compile(rf"(?:job-)?boards(?:-api)?\.greenhouse\.io/(?:v1/boards/|embed/job_board\?for=)?{_TOKEN}", re.I)),
    ("lever", re.compile(rf"jobs\.lever\.co/{_TOKEN}", re.I)),
    ("workable", re.compile(rf"apply\.workable\.com/(?:api/v\d/widget/accounts/)?{_TOKEN}", re.I)),
    ("ashby", re.compile(rf"jobs\.ashbyhq\.com/{_TOKEN}", re.I)),
    ("recruitee", re.compile(rf"{_TOKEN}\.recruitee\.com", re.I)),
    ("breezy", re.compile(rf"{_TOKEN}\.breezy\.hr", re.I)),
)
_IGNORED_TOKENS = frozenset({"embed", "api", "v1", "www", "jobs", "careers", "static", "assets", "js", "css"})


@dataclass
class BoardHit:
    ats: str
    token: str
    api_url: str
    evidence: str
    jobs: int
    ios_titles: list[str] = field(default_factory=list)
    sample_titles: list[str] = field(default_factory=list)
    board_name: str | None = None


def _titles(ats: str, payload: Any) -> tuple[list[str], str | None]:
    if ats == "greenhouse" and isinstance(payload, dict):
        return [str(job.get("title") or "") for job in payload.get("jobs") or []], None
    if ats == "lever" and isinstance(payload, list):
        return [str(job.get("text") or "") for job in payload], None
    if ats == "workable" and isinstance(payload, dict):
        return [str(job.get("title") or "") for job in payload.get("jobs") or []], payload.get("name")
    if ats == "ashby" and isinstance(payload, dict):
        return [str(job.get("title") or "") for job in payload.get("jobs") or []], None
    if ats == "recruitee" and isinstance(payload, dict):
        return [str(job.get("title") or "") for job in payload.get("offers") or []], None
    if ats == "breezy" and isinstance(payload, list):
        return [str(job.get("name") or "") for job in payload], None
    raise ValueError("unexpected payload")


def _api_url(ats: str, token: str) -> str:
    return {
        "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
        "lever": f"https://api.lever.co/v0/postings/{token}?mode=json",
        "workable": f"https://apply.workable.com/api/v1/widget/accounts/{token}",
        "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{token}",
        "recruitee": f"https://{token}.recruitee.com/api/offers/",
        "breezy": f"https://{token}.breezy.hr/json",
    }[ats]


def _probe(ats: str, token: str, evidence: str) -> BoardHit | None:
    url = _api_url(ats, token)
    try:
        payload = fetch_json(url, timeout=_TIMEOUT)
        titles, name = _titles(ats, payload)
    except (requests.RequestException, ValueError, AttributeError):
        return None
    # Workable answers an unknown token with an empty board.
    if not titles and evidence == "slug-guess":
        return None
    return BoardHit(
        ats=ats, token=token, api_url=url, evidence=evidence, jobs=len(titles),
        ios_titles=[title for title in titles if is_ios_job(title)][:10],
        sample_titles=titles[:5], board_name=name,
    )


def _slug_guesses(company: dict[str, Any]) -> list[str]:
    name = str(company.get("name") or "")
    slug = str(company.get("slug") or "")
    compact = re.sub(r"[^a-z0-9]", "", name.lower())
    first = re.sub(r"[^a-z0-9]", "", (name.split() or [""])[0].lower())
    return [value for value in dict.fromkeys((slug, slug.replace("-", ""), compact, first)) if len(value) >= 3]


def _page_hints(career_url: str) -> list[tuple[str, str]]:
    if not career_url:
        return []
    try:
        html = fetch_text_allowing_bot_wall(career_url, timeout=_TIMEOUT) or ""
    except requests.RequestException:
        return []
    hints: list[tuple[str, str]] = []
    for ats, pattern in _PAGE_HINTS:
        for token in pattern.findall(html):
            if token.lower() not in _IGNORED_TOKENS:
                hints.append((ats, token))
    return list(dict.fromkeys(hints))


def discover_company(company: dict[str, Any], *, guess: bool) -> dict[str, Any]:
    career_url = str(company.get("career_url") or "")
    candidates = [(ats, token, "career-page") for ats, token in _page_hints(career_url)]
    if guess:
        candidates += [(ats, token, "slug-guess") for token in _slug_guesses(company)
                       for ats, _ in _PAGE_HINTS]
    hits: dict[tuple[str, str], BoardHit] = {}
    for ats, token, evidence in candidates:
        key = (ats, token.lower())
        if key in hits:
            continue
        hit = _probe(ats, token, evidence)
        if hit:
            hits[key] = hit
    return {
        "name": company.get("name"), "slug": company.get("slug"), "career_url": career_url,
        "boards": [asdict(hit) for hit in hits.values()],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-guess", action="store_true", help="only follow ATS links found on career pages")
    parser.add_argument("--slug", action="append", default=[], help="limit to watchlist slugs")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)

    companies = load_company_watchlist()
    if args.slug:
        companies = [company for company in companies if company.get("slug") in set(args.slug)]
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        results = list(pool.map(lambda company: discover_company(company, guess=not args.no_guess), companies))

    found = [result for result in results if result["boards"]]
    print(json.dumps(found, ensure_ascii=False, indent=2))
    print(f"\nCompanies scanned: {len(results)} · with public ATS boards: {len(found)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
