from __future__ import annotations

from parser.normalize import Vacancy, is_inbox_candidate, is_location_eligible, role_key


def _richness_score(vacancy: Vacancy) -> int:
    score = 0
    if vacancy.description:
        score += len(vacancy.description)
    if vacancy.location:
        score += 10
    if vacancy.published_at:
        score += 5
    if "?" not in vacancy.url:
        score += 1
    return score


def _pick_richer(first: Vacancy, second: Vacancy) -> Vacancy:
    def rank(vacancy: Vacancy) -> tuple[bool, bool, int]:
        return (
            is_inbox_candidate(vacancy),
            bool(vacancy.location) and is_location_eligible(vacancy.location, vacancy.remote),
            _richness_score(vacancy),
        )

    first_score = rank(first)
    second_score = rank(second)
    if second_score > first_score:
        return second
    if second_score == first_score and second.canonical_url < first.canonical_url:
        return second
    return first


def _merge_role_metadata(primary: Vacancy, duplicate: Vacancy) -> Vacancy:
    # Keep the selected variant's requirements/work mode intact for eligibility.
    primary.advertised_locations = tuple(sorted({
        value.strip()
        for value in (*primary.advertised_locations, *duplicate.advertised_locations,
                      primary.location or "", duplicate.location or "")
        if value.strip()
    }))
    # The Telegram mirror of a Hirify posting lacks the board flag; keep it from the API copy.
    primary.russian_company = primary.russian_company or duplicate.russian_company
    return primary


def deduplicate(vacancies: list[Vacancy]) -> tuple[list[Vacancy], int]:
    unique, removed, _ = deduplicate_with_report(vacancies)
    return unique, removed


def deduplicate_with_report(vacancies: list[Vacancy]) -> tuple[list[Vacancy], int, dict]:
    by_identity: dict[str, Vacancy] = {}
    groups: dict[str, list[Vacancy]] = {}
    removed = 0

    for vacancy in vacancies:
        key = vacancy.identity_key or vacancy.hash
        existing = by_identity.get(key)
        if existing is not None:
            chosen = _pick_richer(existing, vacancy)
            by_identity[key] = _merge_role_metadata(chosen, vacancy if chosen is existing else existing)
            groups[key].append(vacancy)
            removed += 1
            continue

        by_identity[key] = vacancy
        groups[key] = [vacancy]

    # Company career pages often publish one role once per city or work mode.
    # Prefer an eligible variant; other locations are display metadata only.
    by_role: dict[tuple[str, str], Vacancy] = {}
    role_keys: dict[tuple[str, str], str] = {}
    role_groups: dict[tuple[str, str], list[Vacancy]] = {}
    for key, vacancy in list(by_identity.items()):
        role = role_key(vacancy.company, vacancy.title)
        role_groups.setdefault(role, []).append(vacancy)
        previous = by_role.get(role)
        if previous is None:
            by_role[role] = vacancy
            role_keys[role] = key
            continue
        chosen = _pick_richer(previous, vacancy)
        other = vacancy if chosen is previous else previous
        _merge_role_metadata(chosen, other)
        by_role[role] = chosen
        removed += 1
        del by_identity[role_keys[role]]
        by_identity[key] = chosen
        role_keys[role] = key

    strategy_counts: dict[str, int] = {}
    duplicate_groups: list[dict] = []
    for key, items in groups.items():
        strategy = (items[0].identity_strategy or "unknown") if items else "unknown"
        strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
        if len(items) <= 1:
            continue
        duplicate_groups.append(
            {
                "identity_key": key,
                "count": len(items),
                "strategy": strategy,
                "items": [
                    {
                        "company": v.company,
                        "title": v.title,
                        "source": v.source,
                        "source_job_id": v.source_job_id,
                        "url": v.url,
                        "canonical_url": v.canonical_url,
                    }
                    for v in items
                ],
            }
        )

    for role, items in role_groups.items():
        if len(items) > 1:
            duplicate_groups.append({
                "role": list(role), "count": len(items), "strategy": "company_title",
                "items": [{"url": item.url, "company": item.company, "title": item.title} for item in items],
            })

    report = {
        "input_count": len(vacancies),
        "unique_count": len(by_identity),
        "duplicates_collapsed": removed,
        "identity_strategies": strategy_counts,
        "duplicate_groups": duplicate_groups,
    }
    return list(by_identity.values()), removed, report
