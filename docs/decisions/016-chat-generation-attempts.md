# ADR 016: Persist one linear Chat turn and its generation attempts

- Status: Accepted
- Date: 2026-09-16
- Last revised: 2026-09-19
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

Chat is a linear, general-purpose LLM conversation rather than a branching or
multi-task execution system. Allowing several unanswered user messages or several
independently retryable attempts in one conversation would make later assistant
messages ambiguous and unnecessarily complicate context and summary ordering.

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

An attempt records its conversation, source user message, immutable submitted
user-content snapshot, effective provider, effective model, non-secret effective
generation configuration, status, partial content when available, normalized
failure information, and lifecycle timestamps. Effective generation values and
the submitted-content snapshot are immutable once the attempt is created.

A conversation has at most one open attempt, where `pending` and `streaming` are
open states. Starting a new turn persists one user message and its pending
attempt atomically. Completing the attempt persists one assistant message and
the completed status atomically. Only a completed assistant message closes the
turn, and only completed assistant content enters ordinary history or model
context. Partial content remains attempt data and is visibly identified as
incomplete whenever it is shown.

A failed or interrupted attempt is terminal history, not an independently
resumable branch. When the final user message has no completed assistant response,
only its latest failed or interrupted attempt is retryable. Retrying creates a
new pending attempt for that same user message. Earlier terminal attempts remain
inspectable but cease to be retry targets. A conversation cannot accept another
user message until the unmatched tail succeeds; the user may instead edit that
tail and retry it later.

Editing is allowed only for the unmatched final user message while no attempt is
open. Editing changes the visible message but does not rewrite earlier attempt
snapshots. The next retry captures the edited content as its own immutable
snapshot. After an attempt completes, its source user message is no longer
editable. Stage 3 adds no separate abandon-tail workflow: editing can replace the
undelivered intent, and deleting the conversation remains available.

Context is assembled before a new message and attempt are persisted. For a retry,
the unmatched tail supplies the current input exactly once and is not also loaded
as completed history. An oversized or otherwise invalid context therefore creates
no attempt and invokes no provider.

A provider error marks the open attempt failed. Cancellation by the stream
consumer marks it interrupted. When a conversation is resumed, its single stale
open attempt is reconciled as interrupted before another retry can begin.

Title generation, rolling summarization, memory extraction, and other
completed-turn side effects run only after the attempt and assistant message
commit successfully. Persist normalized safe failure detail; full provider
diagnostics stay in logs and must not expose credentials.

These invariants are enforced both transactionally in the application and with a
database constraint preventing more than one open attempt per conversation.

## Consequences

- Completed history remains a strict sequence of user/assistant turns.
- A failed tail can be edited and retried later without duplicating its visible
  user message.
- Attempt records preserve lifecycle and invocation provenance without creating
  multiple retry branches.
- The submitted-content snapshot keeps failed-attempt history truthful after an
  edit.
- Summary checkpoints can rely on linear completed-message order.
- Concurrent sends require conversation-level serialization and a database
  uniqueness safeguard.
- General response alternatives and branching remain outside Chat and do not
  inherit Characters retry semantics.

## Alternatives considered

- Allow several incomplete retry targets — not selected because later completion
  can insert irrelevant assistant responses into an otherwise linear chat.
- Delete every failed attempt — not selected because lifecycle, partial output,
  and safe failure information are useful for recovery and inspection.
- Mutate the source message without storing submitted content — not selected
  because it would falsify what an earlier failed attempt actually sent.
- Persist partial output as an assistant message — not selected because context
  and completed-turn side effects could mistake it for a successful turn.
- Retry by adding the same user message again — not selected because it creates
  duplicate visible history.

## Behavioral examples

- A stream emits partial text and fails. The conversation ends with one
  unmatched user message, and that failed attempt is the only retry target.
- The user edits that message and retries. The old attempt retains its original
  submitted snapshot; the new attempt uses the edited content.
- Three sequential retries may leave three terminal historical attempts, but
  only the latest failed or interrupted attempt is actionable.
- A successful retry creates one assistant message, closes the tail turn, and
  permits the next user message.
- Two concurrent send requests cannot create two pending or streaming attempts.
