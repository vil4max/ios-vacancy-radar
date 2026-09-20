# Search topics

The collector gathers native iOS engineering vacancies and hands them over. It
does not decide whether a role suits anyone; it attaches labels that describe
each vacancy.

The only gate is the topic. A collected iOS role must name a native Apple
platform or language in its title; equivalent word order, punctuation and
explicit technology titles such as Senior Swift Engineer are accepted.
Cross-platform and QA titles are outside the topic.

Everything else is a label, not a filter (`vacancy_labels` in
`parser/normalize.py`):

| Label | Meaning |
| --- | --- |
| `junior` | The title is junior-only: junior, jr, intern, internship, trainee or their Ukrainian and Russian equivalents, with no senior-level word beside it |
| `work_mode` | remote, hybrid, onsite or unknown |
| `workable_from_kyiv` | Remote, or a Kyiv office |
| `location_needs_check` | The role may be workable, but the location is missing or the remote scope names a country or region other than Ukraine. Never set on a role that is not workable from Kyiv: there is nothing left to check |
| `work_authorization` | Requirements that must already be held: local work authorization, a work permit or visa, citizenship or permanent residency, a security clearance. A requirement naming Ukraine, an offer to sponsor a visa, and a line the posting marks as preferred do not count |

The Telegram digest shows the same signals as title marks: 🌱 junior, ⚠️ location
needs a check, 🏢 not workable from Kyiv, 🛂 work authorization required.

Company discovery stays broad enough to find title variants. Deduplication runs before the hand-over, so a role advertised in several places is reported once.

Run `python3 scripts/evaluate_search_quality.py` for the curated offline admission benchmark. It does not establish live-source coverage or personal suitability.
