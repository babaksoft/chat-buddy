# Ongoing status

Stage 3 is complete. All 11 slices and the master plan completion criteria are
satisfied. The final quality suite passes with 242 tests passed and the optional
networked OpenAI smoke test skipped by default.

Current: focused Chat repository refactoring — Planned. This work is scheduled
between the completed Stage 3 milestone and Stage 4.

Next product stage: Stage 4 — Build Characters foundations and Ongoing mode.

## Current refactoring

- [ ] **Planned:** Refactor every Chat repository to receive a SQLAlchemy session
  factory rather than a long-lived session instance. Make repository
  implementations own short-lived session and transaction lifecycles while
  preserving atomic multi-row operations.
- [ ] **Planned:** Split generation-attempt lifecycle management out of the
  conversation repository and service into dedicated domain, application, and
  infrastructure classes. Keep conversation and standalone message operations
  in their existing concern.
- [ ] Update composition, fixtures, repository tests, service tests, and Chat
  integration coverage for the new boundaries.
- [ ] Run `scripts/check.sh` and mark the refactoring plan complete.

Detailed execution plan: `work/ongoing/PLAN.md`.
