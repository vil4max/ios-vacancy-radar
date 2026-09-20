# Vacancy feed

The collector hands gathered vacancies over through one JSON file. It visits
every source on schedule, deduplicates and labels, so a consumer reads a short
list of new entries. Who the consumer is and what it does with an entry is
outside this repository.

The feed is a search result. It is written only to the private state store
(`state/database/vacancy_feed.json`, see [operations](operations.md)). `scripts/runtime_state.py` refuses to
refresh or publish it in the checkout of this public repository, and the path
is git-ignored here.

## Contract

```json
{
  "schema_version": 1,
  "vacancies": {
    "<canonical vacancy URL>": {
      "company": "Example Engineering",
      "title": "Senior iOS Engineer",
      "url": "https://example.com/jobs/1",
      "source": "company",
      "location": "Limassol, Cyprus",
      "advertised_locations": [],
      "published_at": null,
      "first_seen": "2026-01-01T09:00:00+00:00",
      "role_key": "example engineering | ios engineer",
      "labels": {
        "junior": false,
        "level": "senior",
        "work_mode": "remote",
        "workable_from_kyiv": true,
        "location_needs_check": true,
        "work_authorization": []
      },
      "language": "en",
      "description": "Plain text, at most 6000 characters",
      "description_truncated": false
    }
  }
}
```

- Entries are keyed by canonical URL, so a key is stable across runs.
- The collector only appends new entries and prunes entries whose `first_seen`
  is older than 30 days. It never edits an entry and never records what the
  consumer did with it.
- The consumer keeps its own processing state on its side, for example the set
  of keys it has handled. It must not write into this file: the collector owns
  it, and a concurrent edit is a merge conflict for the publisher.
- `role_key` is the deduplication key of the role. One role can arrive from
  several sources under different URLs; entries that share a `role_key` describe
  the same opening, so one description per key is enough to read.
- `labels.level` is parsed from the title: junior, middle, senior, lead, staff,
  principal or unknown. The highest tier named wins, and head and architect
  titles sit with lead.
- `description_truncated` is true when the cap cut the text, so requirements
  near the end may be missing. `language` is a script-based guess (en, uk, ru or
  unknown), good enough to route a reader.
- `schema_version` changes when a field is renamed or removed. Added fields keep
  the version, so a consumer should ignore fields it does not know.
- Labels are facts about the posting, described in
  [search topics](search-tracks.md). The collector does not act on them.
- A vacancy is appended after the Telegram digest succeeds and before it is
  marked as seen. A failed feed write fails the hand-over, so the same
  vacancies are retried on the next run rather than lost.
