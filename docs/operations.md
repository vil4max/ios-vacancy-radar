# Operations

GitHub Actions runs the collector through `collect.yml`. `hourly-trigger.yml` dispatches due Kyiv slots at 06:00 and 15:00, using `collect_slots.json` to avoid completing a slot twice.

The collector reads public company career pages, ATS endpoints, the public jobs.dou.ua RSS feeds and the first page of one findmyremote.ai listing (robots.txt respected; see [collector coverage](collector-coverage.md)). Optional Telegram sources need separate reader credentials. Missing optional reader access is reported independently of company coverage: each Telegram source is marked degraded, the run status becomes degraded, and the digest names the channels on a "Telegram без ключей" line.

A @hirifyme_bot message that looks like a vacancy but carries no hirify.me job link is skipped rather than failing the channel. The reader cursor moves past it, so the `skipped` count in the collection diagnostics is the only record; a growing count means the bot changed its message format.

A degraded findmyremote.ai source means the listing page no longer matches the parser. Compare the live page's job cards with `tests/fixtures/findmyremote_listing.html`, fix `collector/findmyremote.py` and the fixture together, and do not add requests to other paths of the site to compensate.

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

Maintain company sources with `scripts/refresh_dou_service_watchlist.py`, `scripts/discover_mobile_companies.py` and `scripts/discover_ats_boards.py`. `discover_mobile_companies.py` registers new iOS or mobile employers by itself. It is incremental: `database/company_discovery_state.json` records when each catalog company was last inspected (slug and date only), so a run inspects new catalog companies plus at most `--recheck` companies older than `--recheck-days` (defaults 300 and 90). Requests to DOU are paced to one every 1.5 seconds, because an unpaced sweep of the whole catalog (about 30,000 requests in an hour) got the client's address blocked by DOU. Run it from a workstation, not from the collection workflow, and use `--dry-run` to see the counts first.

A second LaunchAgent, `local.ios-vacancy-radar.collect-lag-catchup`, compensates for GitHub Actions schedule lag. GitHub documents that `schedule` events can be delayed or dropped under load, so the hourly cron in `.github/workflows/hourly-trigger.yml` often fires only a couple of times a day, hours after the Kyiv 06:00 and 15:00 slots. Every ten minutes the agent runs `scripts/kick_collect_if_due.sh`: it skips if a Collect run is already queued or running, then dispatches `Collect iOS Jobs` when `scripts/should_kick_collect.py` reports a slot that is at least fifteen minutes overdue and not yet recorded in `database/collect_slots.json`. It collects nothing itself and is a supplement, not the primary scheduler: it works only while the Mac is awake and logged in, and the cron path stays as the fallback. Manage it with `scripts/install_collect_kick_launchd.sh install|uninstall|status`; the log is `~/Library/Logs/ios-vacancy-radar-collect-lag-catchup.log`; `RADAR_COLLECT_CATCHUP_DRY_RUN=1` logs the decision without dispatching.

A LaunchAgent runs the discovery weekly: `scripts/install_discovery_launchd.sh install|uninstall|status` installs `local.ios-vacancy-radar.discover-mobile`, which starts `scripts/discover_mobile_weekly.sh` on Saturdays at 10:00 local time (launchd runs a missed slot when the Mac wakes). The job works in a throwaway worktree at `origin/main`, never in the main checkout, and skips the week when `jobs.dou.ua` does not answer 200. The owner gave it standing permission (2026-09-22) to commit and push its own output to `main`. It may touch only `database/company_discovered.json`, `database/company_discovery_state.json` and `database/dou_service_companies.json`, and only after ruff, the tests and the private-data scan pass. Any other change or a failed check aborts the run without publishing. If `main` moved during the run, it rebases once, and a second failure aborts. The log is `~/Library/Logs/ios-vacancy-radar-discovery.log`; `RADAR_DISCOVERY_DRY_RUN=1` commits in the throwaway worktree without pushing. Review discovered URLs before committing them. Sites that reject automated access require manual source inspection; do not bypass access controls.
