# Chat Repository Refactoring Plan

Status: Planned

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

## Plan

1. Change `ConversationRepository`, `MemoryRepository`, and `SummaryRepository`
   implementations to accept a typed session factory. Open and close a session
   per public operation, use repository-owned transaction contexts for writes,
   and pass the active session into internal helpers so nested work remains in
   one transaction. Update Chat composition to pass `ChatSessionLocal` directly.
2. Narrow the domain `ConversationRepository` protocol to conversation and
   message operations. Add a `GenerationAttemptRepository` protocol for attempt
   creation, retries, state transitions, recovery queries, and history.
3. Extract the generation-attempt persistence methods into a dedicated
   infrastructure repository. Keep compound lifecycle operations there so their
   message and attempt writes remain atomic; standalone message operations stay
   in the conversation repository.
4. Add a `GenerationAttemptService` and remove attempt lifecycle methods from
   `ConversationService`. Inject both services into `ChatService`, route each
   operation through its owning service, and update exports, composition, and
   test doubles.
5. Replace shared-session test setup with session-factory fixtures and separate
   inspection sessions. Split repository and service tests by responsibility,
   retain integration coverage for atomic start/completion, rollback, retries,
   stale-attempt reconciliation, and unmatched-message editing, and add checks
   for deterministic session closure and failed-write rollback.
6. Run `scripts/check.sh` and resolve formatting, import, typing, architecture,
   and behavioral regressions before marking the refactor complete.

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
