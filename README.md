# iOS Vacancy Radar

Collect public vacancies, label them, send a Telegram digest, and hand them over through a feed file. See [architecture](ARCHITECTURE.md) for how the parts fit. The collector gathers native iOS/Swift Engineer and Developer roles from official company career pages and ATS endpoints and hands them over with labels (level, work mode, location, work authorization); it does not judge whether a role fits. Optional Telegram sources supplement company coverage.

The tool does not manage candidate profiles, personal salary targets, fit scores, applications, interviews, recruiter correspondence, or email reports.

## Delivery

New vacancies are appended to the [vacancy feed](docs/vacancy-feed.md) in a private store for a consumer outside this repository. Telegram receives new vacancy links and collection health at the configured Kyiv collection slots (11:00 and 15:00). A failed delivery does not complete the collection slot.

Public runtime state contains source baselines, collection slots, and Telegram source cursors. Search results — the discovery history and the hand-over feed — are written only to a private repository; see [operations](docs/operations.md). Never store credentials in this repository.

## Setup

See [operations](docs/operations.md) for running and troubleshooting the collector.

| Secret | Purpose |
| --- | --- |
| `STATE_REPO`, `STATE_REPO_TOKEN` | Required: the private repository that holds the discovery history and the hand-over feed, and a token that can write to it |
| `TELEGRAM_TOKEN` | Bot token for outbound posts |
| `TELEGRAM_CHAT_ID` | Destination chat ID |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION` | Optional: read configured Telegram sources |

`CAREER_AGENT_SEEN_GATE` keeps its legacy name for compatibility.

## Development

Use Python 3.12 and the pinned development dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --require-hashes --only-binary :all: --no-binary pyaes -r requirements-dev.lock
python3 -m ruff check .
bash scripts/smoke-tests.sh
python3 scripts/evaluate_search_quality.py
```

The offline quality benchmark measures curated admission cases, not live market coverage. See [search quality](docs/search-quality.md) and [search topics](docs/search-tracks.md).
