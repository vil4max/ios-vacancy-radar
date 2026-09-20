# Architecture

This repository gathers open vacancies from public sources, labels them, and
hands them over. That is its whole job. It does not decide whether a role suits
anyone, and it does not describe what happens to a vacancy after the hand-over:
that is outside this repository.

```text
  public sources
  ──────────────
  company career pages ─┐
  ATS board APIs ───────┼─► collect ─► normalize ─► deduplicate ─► topic gate
  Telegram channels ────┘                                              │
                                                                       ▼
                                                                    label
                                                                       │
                          ┌────────────────────────┬───────────────────┤
                          ▼                        ▼                   ▼
                   Telegram digest           vacancy feed        discovery state
                                           (hand-over file)        (seen gate)
```

## Stages

1. **Collect** — `collector/` reads official career pages, public ATS board APIs
   (`collector/ats_boards.py`) and optional Telegram channels. A source that
   fails is reported as failed or degraded; it never silently yields nothing.
2. **Normalize** — `parser/normalize.py` turns raw postings into `Vacancy`
   records with a canonical URL and a stable identity.
3. **Deduplicate** — `parser/deduplicate.py` collapses one role advertised in
   several places, and `role_family_key` recognises a re-post of the same role.
4. **Topic gate** — `is_inbox_candidate` keeps a vacancy only if it is on topic:
   a native iOS title. This is the only filter.
5. **Label** — `vacancy_labels` attaches facts about the posting: level, work
   mode, location and work-authorization requirements. Labels never remove a
   vacancy. See [search topics](docs/search-tracks.md).
6. **Seen gate** — `storage/seen.py` holds what was already reported, so a
   vacancy is announced once.
7. **Deliver** — `scripts/run_pipeline.py` sends the Telegram digest, appends the
   new vacancies to the [vacancy feed](docs/vacancy-feed.md), and only then marks
   them seen. A failure at either step leaves them unmarked, so the next run
   retries instead of losing them.

Why the collector labels instead of filtering is recorded in
[ADR 0001](docs/adr/0001-collect-and-hand-over.md).

## Layout

| Path | Holds |
| --- | --- |
| `collector/` | Source adapters: career pages, ATS board APIs, Telegram channels, and the watchlist that drives them |
| `parser/` | Normalization, deduplication, the topic gate and the labels |
| `storage/` | Code that reads and writes runtime state and the hand-over feed |
| `database/` | Data only: the company watchlist, the ATS board map, and the runtime state JSON |
| `reporter/`, `integrations/` | The Telegram digest, the HTTP client and notification formatting |
| `planner/`, `config/` | Collection schedule and its health check |
| `scripts/` | Entry points: the pipeline, the state publisher, the benchmark, and source maintenance tools |
| `tests/` | Offline tests; nothing in them touches the network |

## State and the public boundary

This repository is public. It holds the search mechanism, not search results
and not anything personal; [AGENTS.md](AGENTS.md) is the binding statement of
that boundary and `tests/test_public_boundary.py` enforces it.

| File | Holds | Lives |
| --- | --- | --- |
| `source_baseline.json` | per-source health history | here |
| `collect_slots.json` | which collection slot was completed | here |
| `telegram_cursors.json` | reader positions | here |
| `seen.json` | vacancies already reported | a private store only |
| `vacancy_feed.json` | the hand-over feed | a private store only |

`scripts/runtime_state.py` publishes state by merging into the remote tree, and
`--root` points it at the private store. It refuses to publish a private-only
file from this checkout. See [operations](docs/operations.md).
