# Collector coverage

## Sources

| Layer | What |
|-------|------|
| Python `collector/companies.py` | Orchestrates all company/ATS collectors in parallel |
| Python `collector/generic.py` | Shared HTML helpers (WP REST, HTML regex, BeautifulSoup links) |
| Python `collector/bespoke.py` | Custom career APIs (Andersen, Ciklum, Sigma, DataArt, Grid Dynamics, RBI, …) |
| Python `collector/epam.py` | EPAM sitemap discovery + vacancy `__NEXT_DATA__` (location + remote); `scanned` counts every vacancy URL in the sitemap |
| Python `collector/dou_rss.py` | jobs.dou.ua public RSS: the iOS/macOS category feed, and the `AI` search feed restricted to mobile / iOS / Swift / SwiftUI / Apple / macOS titles |
| Python `collector/company_watchlist.py` | Generic official-page monitor and explicit unresolved-source failures |
| Python `collector/dou_service_ratings.py` | Research-only DOU service-company rating → `database/dou_service_companies.json` watchlist |
| Python `collector/dou_top50.py` | Research-only DOU Top 50 discovery; adds companies only when an official career URL is verified |
| Python `collector/dou_catalog.py` | Research-only DOU companies catalog → `database/dou_companies.json` |
| Python `collector/mobile_discovery.py` | Finds catalog companies whose own careers page or DOU vacancy titles name iOS or a mobile stack; `scripts/discover_mobile_companies.py` registers them in `database/company_discovered.json` |
| Python `collector/telegram_channels.py` | Telegram chats (MTProto / Telethon): `@itrecruit_ua`, `@remotejobss`, `@itfreelancers`, `@mobile_jobs` |

The production registry contains official career sites and ATS endpoints of large Ukrainian or Ukraine-active **service / outsourcing** companies. Djinni is intentionally excluded because it is covered by user subscriptions. DOU vacancies enter only through its two public RSS feeds (`collector/dou_rss.py`): some employers' own career sites refuse automated clients with HTTP 403 while DOU still lists their roles, and a subscription does not reach the hand-over feed. The RSS entries pass the same topic gate and labels as every other source; the company and location come from the item title (`<Role> в <Company>, <locations…>`), salary segments are dropped, and links lose their `utm_*` parameters. The DOU HTML pages remain research input for the company watchlist only. Telegram remains supplementary and does not count as official company coverage.

Company size is not a condition for iOS hiring, so the watchlist also grows from the whole DOU catalog. `scripts/discover_mobile_companies.py` reads every catalog company that is not yet registered. From the DOU profile it finds the company site, then the careers page, following one "all vacancies" link and up to five pages of pagination. It adds the company when that page, or the company's current DOU vacancy titles, names iOS/Swift or a mobile stack (Android, Flutter, React Native, KMM), and when the watchlist collector parses that page. A bare "mobile" is not enough: it is usually benefit text. An App Store link on a homepage does not count either. A site that answers 403, a client-rendered shell and a missing careers page are skipped, not worked around; the DOU RSS feed still carries their DOU postings. Additions go to `database/company_discovered.json`, which the watchlist refresh merges like the manual additions, so a refresh does not drop them. The script prints counts only, and is incremental and paced; see [operations](operations.md).

The watchlist is coverage-first: service-rating companies with 200+ specialists form the baseline, and Top 50 companies are added only after their official career URL is verified. Verified URL overrides live in `database/company_career_overrides.json`; explicitly retained companies outside the current DOU snapshots live in `database/company_manual_additions.json`, so every production collector remains visible and can be disabled. Company metadata stays deliberately small: overall DOU rating, compensation rating, survey count, and enabled state. A company whose career page is a public ATS board is collected through that board's API instead: `collector/ats_boards.py` supports Greenhouse, Lever, Ashby, Breezy, Recruitee and Workable, and `scripts/discover_ats_boards.py` probes exactly that set so a discovered board can be added to `database/company_ats_boards.json` unchanged. An entry naming an unsupported ATS, or missing its token, is skipped with a warning and the company falls back to its career page; the board map is loaded once per run, so one bad entry must not fail every company. Collector crashes are visible failures; repeated zero-scan pages become degraded rather than being treated as trustworthy empty results.

## Match policy

Discovery retains broad Apple-platform signals, and the topic gate keeps native
iOS/Swift titles. QA/test automation/TPM and cross-platform roles are outside
the topic. Every iOS level is collected; a junior-only title is labelled rather
than dropped. Geography, work mode, level and work-authorization requirements do
not remove a vacancy either: they are attached as labels; see
[search topics](search-tracks.md).

JSON-LD JobPosting descriptions and locations, including nested graphs, enrich
listing anchors. WordPress and Conscensia retain rendered descriptions already
returned by their APIs. DataArt and Luxoft add an unfiltered category or
specialization pass beside the iOS query, so a mis-categorised iOS role is still
found; a failed secondary pass preserves primary results with degraded status.
Company/title multi-geo variants collapse to one role with separately listed
advertised locations and an eligible application URL.

## Recovery boundaries

RBI discovery reads its sitemap and career listing independently. A failed path
keeps verified jobs from the other path and reports degraded coverage. Detail
failures and page limits are explicit; if every discovered detail fails, the
source fails. A sitemap slug alone never creates a vacancy title.

A successful unit test or indexed search result does not prove live HTTP
availability. AltexSoft career listing and RBI career listing returned HTTP 403
during the 2026-09-09 public-page check; RBI sitemap returned HTTP 200. No new
ATS endpoint, anti-bot bypass, or alternative production feed was introduced.

## Request budgets

The shared GET client permits two concurrent requests per hostname and at most
three attempts per GET. HTTP 429 and 5xx use `Retry-After` seconds or HTTP dates;
a required delay above 30 seconds fails this attempt instead of retrying early.
Without a valid header the retry delays are 0.4 and 0.8 seconds. Impersonation
fallbacks share the domain limit and cannot restart exhausted rate-limit retries.
Custom clients outside the shared HTTP module retain their existing behavior.
