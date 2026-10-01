# Operational state

Working notes of the standing session that operates the collector. Neutral
operational facts only: no findings, no personal data, no secrets.

## Role and scope

The `ios-vacancy-radar` session owns the operation of this repository
(decision of 2026-10-01) and answers questions about the collector.

- Keep the on-time scheduler working: the local launchd agent
  `local.ios-hunter.collect-kick`, the `Collect Schedule Trigger` workflow and
  the slot state in `database/collect_slots.json`.
- Read run statistics: workflow runs, slot timing, per-source health and the
  Telegram delivery result of each run.
- Add and test sources on request (brief, collector module, offline tests with
  synthetic fixtures, a line in `docs/collector-coverage.md`).
- Report feed changes to the feed consumers.

Out of scope: judging which vacancy suits anyone, secrets, private data, a
production pipeline run from a workstation, and repository administration.

## Current state

- Registered in the kit session registry as a standing role (2026-10-01).
- Scheduler: the launchd agent is loaded and its log advances every ten
  minutes; slot 06:00 Kyiv of 2026-10-01 is completed.
- Slot 15:00 Kyiv of 2026-10-01: not yet due at the time of writing.

## Open questions

- Which sources in the latest digest report no answer or block automatic
  collection, and what is the cause of each (first task, in progress).

## Next step

1. Confirm the 15:00 Kyiv slot is dispatched by about 15:15.
2. Classify the failing sources from the run logs and propose the smallest fix
   inside the repository rules.
