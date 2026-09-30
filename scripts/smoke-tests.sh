#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m pytest -q
python3 -c "from collector.companies import collect_all; from storage.seen import load_seen; from storage.vacancy_feed import append_feed; from reporter.hourly import format_hourly_new_vacancies"
