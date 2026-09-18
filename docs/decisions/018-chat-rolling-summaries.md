# ADR 018: Persist checkpointed conversation-scoped Chat summaries

- Status: Accepted
- Date: 2026-09-18
- Last revised: 2026-09-19
- Refines: ADRs 016 and 017

## Context

The Chat prototype creates a transient summary of half the message list whenever
its combined context crosses a fixed ratio. It does not persist the summary or
record which completed turns it represents, so repeated context builds can
resummarize the same content.

ADR 016 makes Chat history linear: a conversation cannot advance beyond an
unmatched user tail, and a retry must resolve that tail before another message is
accepted. A completed turn therefore cannot appear behind a later completed turn.
Summary coverage does not need a second per-attempt provenance graph.

## Decision

Persist versioned summaries owned by one Chat conversation. A version records a
stable identifier, content, creation time, lifecycle state, optional predecessor,
and a checkpoint identifying the newest assistant message incorporated by the
version. Summary states are `active` and `superseded`; at most one version is
active per conversation. Creating a replacement and superseding its predecessor
are one transaction.

The predecessor and checkpoint provide the summary's provenance. The checkpoint
is authoritative because ADR 016 guarantees a linear sequence of completed
turns. A first version advances from no checkpoint to the assistant message of
the newest summarized turn. A rolling replacement advances from the active
checkpoint to a newer assistant message. A summary-only compaction successor may
retain the same checkpoint but can never move it backward.

A summary may cover only a chronological prefix of complete turns from its own
conversation. A first version consumes the oldest eligible complete turns. A
rolling replacement consumes the active summary plus the oldest complete turns
after its checkpoint. It retains at least the configured minimum number of most
recently completed turns outside the summary. The initial minimum is two complete
turns.

Summarization is considered when all eligible formatted context exceeds ADR
017's summary trigger. The service summarizes as many oldest uncovered complete
turns as necessary and available while retaining the minimum recent turns. It
never summarizes current input, an unmatched user message, partial output, a
failed or interrupted attempt, or a turn at or before the active checkpoint.

If the active summary is too large for a newly selected model, the service may
create a compacting successor at the same checkpoint. It is accepted only when
it reduces the selected model's formatted summary cost toward the target.

If summary generation, validation, or persistence fails, the active summary and
checkpoint remain unchanged. ADR 017's budgeter then uses the last durable
summary, omits optional inputs where necessary, and fails if mandatory content
does not fit. A later context build may retry. Stage 3 adds no background repair.

Deleting a conversation hard-deletes its summaries. A summary never becomes Chat
memory and is never eligible in another conversation or in Characters.

## Consequences

- Long conversations reuse durable summaries without repeatedly processing the
  same complete turns.
- Version lineage preserves replacement and failure history.
- A single checkpoint is sufficient because completed Chat history is linear.
- No summary-source association table or late-retry coverage scan is required.
- Model switching may create a summary-only compaction version.
- Summary failure cannot corrupt the last known-good version.

## Alternatives considered

- Store one mutable summary — not selected because it loses version history and
  last-known-good recovery.
- Persist every covered attempt on every summary version — not selected because
  linear completion order makes that duplicate provenance unnecessary.
- Rebuild from all historical messages — not selected because it repeatedly
  processes already summarized content.
- Share summaries across conversations — not selected because summaries contain
  conversation-specific history rather than Chat-wide user facts.

## Behavioral examples

- When context crosses the trigger, Chat summarizes the oldest complete turns,
  checkpoints their newest assistant message, and retains two recent turns.
- A failed tail contributes nothing. Its retry must complete before the
  conversation advances and then appears naturally after the prior checkpoint.
- If summary generation fails, the prior version and checkpoint remain active.
- Switching to a smaller model may compact the active summary while retaining
  exactly the same checkpoint.
