# Operations

GitHub Actions runs the collector through `collect.yml`. `hourly-trigger.yml` dispatches due Kyiv slots at 11:00 and 15:00, using `collect_slots.json` to avoid completing a slot twice.

The collector reads public company career pages and ATS endpoints. Optional Telegram sources need separate reader credentials. Missing optional reader access is reported independently of company coverage: each Telegram source is marked degraded, the run status becomes degraded, and the digest names the channels on a "Telegram без ключей" line.

A @hirifyme_bot message that looks like a vacancy but carries no hirify.me job link is skipped rather than failing the channel. The reader cursor moves past it, so the `skipped` count in the collection diagnostics is the only record; a growing count means the bot changed its message format.

Production sets `REQUIRE_TELEGRAM_DELIVERY=1`: missing outbound bot credentials fail before collection. Failed delivery must be repaired before enabling scheduled runs.

The Telegram digest is a short notice: the new vacancies with their links, and one status line. When sources fail it names them and nothing more. Inspect the collection diagnostics artifact for the reasons, URLs and counters, and the Actions summary for errors. Runtime recovery handles only public discovery state. Do not upload credentials or the private store as artifacts.

## Runtime state stores

The collector keeps five runtime files in two places.

Three describe the mechanism and live in this public repository:
`source_baseline.json` (per-source health), `collect_slots.json` (which
collection slot was completed) and `telegram_cursors.json` (reader positions).

Two are search results and live only in a private repository: `seen.json`, the
vacancies already reported, and `vacancy_feed.json`, the
[hand-over feed](vacancy-feed.md). Both keep the `database/` path inside that
repository. The workflow checks it out into `state/`, which is git-ignored here.

There is no public fallback. The workflow stops at "Require the private state
store" unless both secrets exist, because starting from an empty history would
announce every known vacancy again. `scripts/runtime_state.py` refuses to
refresh or publish either file unless `--root` points at a separate checkout,
and neither file is ever part of the collection recovery artifact: artifacts of
a public repository are downloadable. Recover them from the private
repository's own history.

| Secret | Value |
| --- | --- |
| `STATE_REPO` | `owner/name` of the private repository. It is a private destination identifier, so it is a secret and is never committed here |
| `STATE_REPO_TOKEN` | A fine-grained token limited to that repository with Contents read and write |

Earlier versions of `seen.json` remain in this repository's history from before
the move; deleting the file did not remove them.

For an intentional local baseline without delivery, run `python3 scripts/run_pipeline.py --seed-only`. This marks current discoveries as seen; it does not notify or hand anything over. Avoid using it as a delivery test because it suppresses future notifications for those identities.

Maintain company sources with `scripts/refresh_dou_service_watchlist.py` and `scripts/discover_ats_boards.py`. Review discovered URLs before committing them. Sites that reject automated access require manual source inspection; do not bypass access controls.
