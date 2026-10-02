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

## Source health (runs of 2026-09-30 and 2026-10-01, run logs)

Latest run (workflow_dispatch, 2026-10-01 09:34 UTC): 7 failed, 7 degraded
in the log; delivery accepted 1 message. Persistent across the last three runs:

| Class | Sources | Evidence |
| --- | --- | --- |
| Blocked by the site (HTTP 403 from the runner) | Apriorit, PUMB, YozmaTech, ARTJOKER, Aks.ua, Grand Car, AUTOBAZA, Aweb, MacPaw (Recruitee API) | same 403 in all three runs; Apriorit, PUMB, YozmaTech and the MacPaw API also answer 403 to an honest-UA probe from a workstation |
| Rate limited | Checklist.com (429), Agilites (Retry-After above the 30 s budget) | `integrations/http_client.py` budget errors in all three runs |
| Dead address | SoftHouseGroup (404 on the registered careers-page path, which its own homepage still links) | succeeded 2026-09-30 03:25 UTC, 404 since |
| Temporary | Luxoft (502, also 502 from a workstation) | succeeded 2026-09-30 16:27 UTC |
| Parser or content out of date, to verify | Ciklum (0 items, 17 empty runs), AltexSoft (0 items, 4 runs; listing blocked 2026-09-09), Geniusee, Blynk, Qubit Labs, Aladdinb2b, Aston VIP (0 items after earlier non-zero) | `source_baseline.json` |

Actions of 2026-10-01 (owner decision relayed by the orchestrator):

- The 403 sources already go to the digest line "Блокируют автосбор" and are not
  counted in "Sources failed" (`is_access_blocked` in `collector/results.py`),
  so no change was needed. Only Luxoft (502), Checklist.com (429), Agilites
  (Retry-After) and SoftHouseGroup (404) counted as failed in the latest run.
- Aks.ua: careers-page address switched to the https www form. A workstation reads
  both forms as healthy, so the runner 403 may be address-independent; the next
  runs show whether it changed anything.
- SoftHouseGroup: disabled in the watchlist with a dated reason, until its
  careers path is re-verified.

## Open questions

- Zero-item sources: Ciklum (17 empty runs), AltexSoft (4 runs), Geniusee,
  Blynk, Qubit Labs, Aladdinb2b, Aston VIP. Parsers stay untouched without a
  brief. Next check: 2026-10-08, against `source_baseline.json` and the live
  pages one at a time.
- The Aks.ua runner 403 and the SoftHouseGroup address: re-check on 2026-10-08.

- Moving the private state store to another repository is on hold (owner,
  2026-10-02). The plan is kept in the agent bank. No step of it is run, not
  even pausing the local dispatch agent, until the orchestrator brings the
  owner's word. The collector stays on its current store.

## Next step

1. Confirm the 15:00 Kyiv slot is dispatched by about 15:15.
2. Read the next scheduled run and compare the failed and blocked lines.
