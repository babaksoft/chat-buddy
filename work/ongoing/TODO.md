# Ongoing status

Stage 3 is complete. All 11 slices and the master plan completion criteria are
satisfied. The final quality suite passes with 242 tests passed and the optional
networked OpenAI smoke test skipped by default.

Current: focused Chat repository refactoring — In progress. Slices 1 and 2 are
complete; Slice 3, moving repositories to repository-owned short-lived sessions,
is next. This work is scheduled between the completed Stage 3 milestone and
Stage 4.

Next product stage: Stage 4 — Build Characters foundations and Ongoing mode.

## Current refactoring

- [ ] **In progress:** Refactor every Chat repository to receive a SQLAlchemy session
  factory rather than a long-lived session instance. Make repository
  implementations own short-lived session and transaction lifecycles while
  preserving atomic multi-row operations.
- [x] **Slice 2:** Split generation-attempt lifecycle management out of the
  conversation repository and service into dedicated domain, application, and
  infrastructure classes. Keep conversation and standalone message operations
  in their existing concern.
- [x] **Slice 1:** Add the session-factory test seam and characterize atomic
  generation start, completion, and rollback through separate inspection
  sessions.
- [x] Update composition, fixtures, repository tests, service tests, and Chat
  integration coverage for the new boundaries.
- [ ] **Next — Slice 3:** Give Chat repositories typed session factories and
  repository-owned short-lived session and transaction lifecycles.
- [ ] Run `scripts/check.sh` and mark the refactoring plan complete.

Detailed execution plan: `work/ongoing/PLAN.md`.
