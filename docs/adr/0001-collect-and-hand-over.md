# ADR 0001: The collector gathers and hands over; it does not judge

Status: accepted, 2026-09-20.

## Context

The collector decided what to deliver. It dropped vacancies by seniority, by
geography, by work mode and by work-authorization requirements. Those rules
silently removed vacancies: a remote role scoped to the EU was dropped as
"foreign", and lead roles were dropped by a senior-only title rule. A filter
that is wrong fails invisibly, because nobody ever sees the dropped vacancy.

Selection criteria are specific to each consumer of the vacancies, so they do
not belong in a general-purpose public collector.

## Decision

The collector gathers open vacancies, deduplicates them, attaches labels, and
hands them over. The only filter is the topic: a native iOS title. Level, work
mode, location and work-authorization requirements become labels
(`vacancy_labels`) that travel with the vacancy in the Telegram digest and in
the hand-over feed.

What is done with a handed-over vacancy is outside this repository.

## Consequences

- A wrong label is visible and cheap: the vacancy still arrives, marked. A wrong
  filter was invisible and lost the vacancy.
- Delivery volume grows. Junior roles, foreign offices and roles requiring local
  work authorization now arrive, marked.
- Selection criteria stay outside the collector.
- The labels are computed once, here, by tested code, so a consumer can sort
  vacancies by them instead of re-deriving the same signals from descriptions.
- The feed and the discovery history are search results, so they can live in a
  private store; see [operations](../operations.md).

## Alternatives considered

- **Keep filtering and tune the rules.** Rejected: each tuning round repeats the
  same invisible failure, and the criteria stay in the collector.
- **Hand over raw postings without labels.** Rejected: every consumer would have
  to re-derive the same signals, duplicating logic that exists and is tested
  here.
- **Replace scheduled collection with on-demand browsing of the sources.**
  Rejected: coverage would not be reproducible, and a fixed crawl of every
  source on a schedule is exactly the deterministic work code is suited to.
