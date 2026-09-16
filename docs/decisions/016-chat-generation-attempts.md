# ADR 016: Persist Chat generation attempts explicitly

- Status: Accepted
- Date: 2026-09-16
- Refines: ADR 014

## Context

Chat persists a user message before response streaming begins and persists the
assistant message only after the stream completes. A provider failure therefore
leaves an unanswered user message without a durable explanation or retry target.
Consumer cancellation and process interruption can also end a stream without
passing through ordinary exception handling.

Provider and model selection may change during a conversation. Conversation-level
configuration alone cannot reproduce or explain which effective configuration
produced an earlier response.

## Decision

Store the current requested provider, model, and generation configuration on the
conversation. Treat those values as defaults for its next response, not as the
historical provenance of every response.

Represent each response invocation as a generation attempt with the following
lifecycle:

```text
pending -> streaming -> completed
                     -> failed
                     -> interrupted
```

An attempt records its conversation, source user message, effective provider,
effective model, non-secret effective generation configuration, status, partial
content when available, normalized failure information, and lifecycle
timestamps. Effective generation values are immutable once the attempt begins.

Starting a new turn persists the user message and pending attempt atomically.
Completing an attempt persists the assistant message and completed status
atomically. Only the content of a completed assistant message belongs to normal
conversation history or model context. Partial content belongs to the attempt
and must be visibly identified as incomplete whenever it is shown.

A provider error marks the attempt failed. Cancellation by the stream consumer
marks it interrupted. When a conversation is resumed, an unresolved attempt that
is no longer owned by an active stream is reconciled as interrupted.

Retrying an incomplete attempt creates a new attempt for the same source user
message. It does not duplicate the user message or turn the previous partial
content into an assistant message. Title generation, memory extraction, and
other completed-turn side effects run only after the attempt and assistant
message have been committed successfully.

Persist a normalized error code and safe user-facing detail when useful. Full
provider diagnostics belong in logs and must not copy credentials or other
sensitive provider data into the database.

## Consequences

- Completed history remains unambiguous after provider failures and consumer
  cancellation.
- Every completed assistant response has immutable provider, model, and
  generation-configuration provenance through its attempt.
- Retry behavior can recover an unanswered user turn without duplicating it.
- Repositories need explicit transactional operations for starting and
  completing attempts.
- Partial-content checkpointing must balance recoverability against database
  write frequency.
- This recovery model does not introduce general response alternatives or Chat
  branching; those remain separate from Characters retry and branching rules.

## Alternatives considered

- Delete the user message when streaming fails — not selected because it loses a
  durable record of user intent and makes recovery dependent on UI state.
- Persist a partial assistant message in ordinary history — not selected because
  later context and completed-turn side effects could treat it as a valid turn.
- Store provenance only on the conversation — not selected because changing the
  selected provider or model would make earlier responses ambiguous.
- Retry by adding the same user message again — not selected because it creates
  duplicate history and changes the context sent to the provider.

## Behavioral examples

- If a stream emits text and then fails, Chat records a failed attempt with its
  partial content while completed history still ends at the source user message.
- Retrying that attempt reuses the source user message and creates a new immutable
  effective-configuration snapshot.
- Switching models affects the next attempt; earlier assistant messages retain
  the provenance of the models that produced them.
