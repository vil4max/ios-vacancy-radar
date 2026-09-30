# Search admission regression benchmark

Run `.venv/bin/python scripts/evaluate_search_quality.py` locally. It reads only
`tests/fixtures/search_quality.json`; it does not collect, notify or change
runtime state. CI runs it and includes its JSON report in the summary. Any
admission, location-warning, label or duplicate-selection mismatch fails the
command. Unit tests also prove that incorrect expectations are detected.

The set contains 15 admission cases and three duplicate groups tested in both
discovery orders. It covers native iOS titles across levels, Kyiv, remote and
unknown geography, foreign remote scopes and foreign offices, junior titles,
work-authorization requirements, and the roles that stay outside the topic:
cross-platform, desktop and non-engineering titles. Because the collector
labels rather than filters, most cases assert that a vacancy is handed over
and which labels it carries. Duplicate checks require the eligible URL to win
over a foreign variant and retain distinct roles.

One case paraphrases a public vacancy's requirements, with its source URL and
capture date inside the fixture. Other cases are explicitly synthetic boundary
cases; company names and application URLs are placeholders. No recruiter
contacts, candidate profile or full vacancy pages are stored.

Precision and recall describe only this curated dataset. They do not measure
unseen vacancies, live discovery coverage or source availability. Operational
source health and liveness diagnostics remain separate evidence.

For a confirmed false admission or missed role, add the smallest paraphrased
case that preserves the relevant requirements and its provenance. Do not weaken
expectations merely to turn CI green. Re-check dated public examples when the
topic policy changes; saved fixtures are not claims that those jobs remain open.
