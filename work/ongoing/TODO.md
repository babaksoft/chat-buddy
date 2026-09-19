# Remaining tasks in current stage

Stage 3 is in progress. Slices 1–2 are complete; Slices 3–11 remain Planned in
`work/ongoing/PLAN.md`.

Next: Slice 3 — Persist linear retries, summaries, and memory lifecycle.

## Focused refactoring backlog

- Refactor every Chat repository to receive a SQLAlchemy session factory rather
  than a long-lived session instance. Define session and transaction ownership,
  keep each atomic multi-row operation on one short-lived session, close sessions
  deterministically, and update composition and repository tests. Deliver this
  as a separate focused change rather than folding it into a Stage 3 feature
  slice or the conversation/attempt repository split.
