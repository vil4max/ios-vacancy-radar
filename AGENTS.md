# iOS Vacancy Radar

A Python tool that collects public native iOS/Swift vacancies from company
career pages, ATS board APIs, the jobs.dou.ua RSS feeds and optional Telegram
channels. It deduplicates and labels them, sends a Telegram digest and appends
new entries to a hand-over feed. It does not rank or judge vacancies.

See [README.md](README.md) for setup and [ARCHITECTURE.md](ARCHITECTURE.md) for
the pipeline stages.

## Layout

- `scripts/run_pipeline.py`: collection, admission, deduplication and delivery.
- `collector/`, `parser/`: public sources and deterministic vacancy normalization.
- `storage/vacancy_feed.py`: the hand-over feed.
- `reporter/hourly.py`: the Telegram digest.
- `scripts/runtime_state.py`: runtime state recovery and publishing.
- `database/`: the company watchlist, the ATS board map and runtime state.
- `tests/`: offline tests with synthetic fixtures; nothing touches the network.

## Public repository

Everything committed here is public. Do not commit credentials, tokens, session
strings, private keys, personal contact details or private destination
identifiers; keep them in GitHub Actions secrets or ignored local environment
files. Search results (specific matched vacancies and the hand-over feed) are
written to a private store configured by the operator, not to this repository.
Use synthetic examples ("Example Engineering", "Limassol, Cyprus") in tests and
documentation. `tests/test_public_boundary.py` enforces this boundary.

## Tests

Production uses Python 3.12. From a virtual environment with the pinned
development dependencies:

```bash
python3 -m ruff check .
bash scripts/smoke-tests.sh
python3 scripts/evaluate_search_quality.py
```

Keep `requirements*.lock` aligned with `requirements*.txt`. Do not run a live
delivery as an offline test.
