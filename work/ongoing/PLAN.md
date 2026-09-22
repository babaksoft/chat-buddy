# Chat Repository Refactoring Plan

Status: In progress — Slices 1–2 complete; Slice 3 next

Last updated: 2026-09-22

## Scope

Refactor Chat persistence so every repository receives a SQLAlchemy session
factory and owns its short-lived session and transaction lifecycle. Separately,
split conversation and message handling from generation-attempt lifecycle
management at the domain, application, and infrastructure boundaries.

The refactor must preserve the existing atomic writes at generation boundaries:
starting an attempt persists its source user message and pending attempt together,
and completing an attempt persists its assistant message and terminal attempt
state together. No database model or migration change is expected.

## Execution slices

The work is divided into four independently testable slices. Boundaries are
separated before transaction ownership changes so persistence methods are not
moved and structurally refactored in the same slice.

### Slice 1: Test harness and invariant characterization — Complete

- [x] Add a typed session-factory fixture while temporarily retaining the
  existing session fixture for current repository constructors.
- [x] Use separate repository and inspection sessions to characterize successful
  atomic generation start and completion.
- [x] Characterize rollback of both compound operations through a separate
  inspection session.
- [x] Record deterministic repository-owned session closure as an acceptance
  check to activate when repositories begin receiving factories.
- [x] Run the focused database repository and Chat integration tests.

This slice changes no production behavior.

### Slice 2: Extract generation-attempt ownership end to end — Complete

- [x] Add a domain `GenerationAttemptRepository` protocol for attempt creation,
  retries, state transitions, recovery queries, and history.
- [x] Narrow `ConversationRepository` to conversation and standalone message
  operations.
- [x] Extract generation-attempt persistence into a dedicated infrastructure
  repository. Keep source-message creation and assistant-message completion in
  that repository so each compound write remains atomic.
- [x] Add `GenerationAttemptService`, remove attempt lifecycle methods from
  `ConversationService`, and inject both services into `ChatService`.
- [x] Update exports, composition, test doubles, repository tests, service tests,
  integration tests, and architecture coverage for the new responsibility
  boundary.

Repositories continue using the existing shared-session construction during
this slice so it remains focused on ownership boundaries.

### Slice 3: Move repositories to repository-owned sessions

- [ ] Change Conversation, Generation Attempt, Memory, and Summary repository
  implementations to accept a typed SQLAlchemy session factory.
- [ ] Open and close one session per public operation and use repository-owned
  transaction contexts for writes.
- [ ] Pass the active session into private helpers so nested work and compound
  lifecycle operations remain in one transaction.
- [ ] Update Chat composition to pass `ChatSessionLocal` directly and hold no
  long-lived session.
- [ ] Convert repository and integration tests to factory construction and
  separate inspection sessions.
- [ ] Add deterministic session-closure checks and retain failed-write rollback
  coverage.

### Slice 4: Consolidation and completion

- [ ] Remove transitional fixtures, constructors, helpers, and stale test
  doubles.
- [ ] Verify exports and Chat architecture boundaries.
- [ ] Confirm no Chat repository accepts a live session and composition creates
  none.
- [ ] Run `scripts/check.sh` and resolve formatting, import, typing,
  architecture, and behavioral regressions.
- [ ] Mark this plan and the ongoing TODO complete only after the full suite
  passes.

## Completion criteria

- No Chat repository is initialized with a live session.
- Repository public operations deterministically close their sessions and own
  transaction commit or rollback.
- Conversation services and repositories no longer expose generation-attempt
  lifecycle operations.
- Generation start and completion retain their current atomic multi-row
  behavior.
- Chat composition holds no long-lived SQLAlchemy session.
- The complete repository quality suite passes.
