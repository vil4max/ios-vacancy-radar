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

## State

As of 2026-10-04:

- Registered in the kit session registry as a standing role; project context
  marker installed (`kind: personal`, profile `core`).
- Scheduler healthy: the launchd agent log advances every ten minutes; slots
  were dispatched on time on 2026-10-01 to 2026-10-04 (latest run 2026-10-04
  03:17 UTC, success).
- Moving the private state store to another repository is on hold (owner,
  2026-10-02). The plan is kept in the agent bank. No step of it is run, not
  even pausing the local dispatch agent, until the orchestrator brings the
  owner's word. The collector stays on its current store.
- Closed requests: digest push to the feed consumer (kept pull-only via the
  hand-over feed), DOU news (moved to another digest, not the radar), DOU
  iOS/macOS category (read in full through its RSS feed), a company whose
  "Mobile Engineer" titles are dropped by the title check (rule kept).
- Weekly discovery launchd agent is documented in `docs/operations.md` but not
  installed; the owner decides.
- Unused secrets and variables with legacy names exist in repository
  settings; removal is the owner's decision.

## Baselines

Source health (run logs 2026-09-30 to 2026-10-01; recheck 2026-10-08):

| Class | Sources |
| --- | --- |
| Blocked by the site (HTTP 403 from the runner), shown on the digest line for blocked sources, not counted as failed | Apriorit, PUMB, YozmaTech, ARTJOKER, Aks.ua, Grand Car, AUTOBAZA, Aweb, MacPaw (Recruitee API) |
| Rate limited | Checklist.com (429), Agilites (Retry-After above the 30 s budget) |
| Dead address, disabled in the watchlist with a dated reason | SoftHouseGroup |
| Temporary | Luxoft (502) |
| Zero items after earlier non-zero, parsers untouched without a brief | Ciklum, AltexSoft, Geniusee, Blynk, Qubit Labs, Aladdinb2b, Aston VIP |

Changes made on 2026-10-01: Aks.ua careers-page address switched to the https
www form (a workstation read both forms as healthy, so the runner 403 may be
address-independent); SoftHouseGroup disabled; `disabled_reason` survives the
weekly watchlist refresh.

## Open questions

- Does the Aks.ua runner 403 persist after the address change?
- Is the SoftHouseGroup careers path back?
- Zero-item sources: still empty on 2026-10-08?

## Next step

Next step: on 2026-10-08 read the latest scheduled run's failed, blocked and
degraded lines against this baseline, check the open questions above one source
at a time, and update this file. Until the orchestrator brings the owner's
word, do nothing on the state-store move.
