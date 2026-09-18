# ADR 018: Persist versioned conversation-scoped Chat summaries

- Status: Accepted
- Date: 2026-09-18
- Refines: ADRs 016 and 017

## Context

The Chat prototype creates a transient summary of half the message list whenever
its combined context crosses a fixed ratio. It does not persist the summary or
record which completed turns it represents. Repeated context builds can therefore
resummarize the same content, and a timestamp-only checkpoint would mishandle an
old failed turn that completes after newer turns have been summarized.

Stage 3 needs durable rolling summaries that never cross conversation boundaries
and remain explainable across retries and model changes.

## Decision

Persist versioned summaries owned by one Chat conversation. A version records a
stable identifier, content, creation time, lifecycle state, optional predecessor,
newly covered completed generation attempts, and a checkpoint identifying the
newest assistant message incorporated by that version. Summary states are
`active` and `superseded`; at most one version is active per conversation.
Creating a replacement and superseding its predecessor are one transaction.

The predecessor chain plus each version's explicitly covered attempts is the
authoritative provenance. The checkpoint is an ordering optimization, not the
sole coverage test. A late successful retry therefore remains uncovered and
eligible even if its source user message predates the checkpoint.

A summary may cover only complete turns from its own conversation. A first
version consumes the oldest eligible complete turns. A rolling replacement
consumes the active summary plus the oldest newly eligible complete turns. It
retains at least the configured minimum number of most recently completed turns
outside the summary. The initial minimum is two complete turns.

Summarization is considered when all eligible formatted context exceeds ADR
017's summary trigger. The service summarizes as many oldest uncovered complete
turns as necessary and available while retaining the minimum recent turns. It
never summarizes current input, an unmatched user message, partial content, an
incomplete attempt, or a turn already in the active summary lineage.

If the active summary is too large for a newly selected model, the service may
create a compacting successor without adding newly covered turns. The successor
inherits the predecessor's effective coverage. It is accepted only when it
reduces the selected model's formatted summary cost toward the target.

If generation, validation, or persistence fails, the active summary and its
provenance remain unchanged. ADR 017's budgeter then uses the last durable
summary, omits optional inputs where necessary, and fails if mandatory content
does not fit. A later context build may retry. Stage 3 adds no background repair.

Deleting a conversation hard-deletes its summaries. A summary never becomes
Chat memory and is never eligible in another conversation or in Characters.

Additive provenance metadata and stronger validation are compatible updates when
they preserve conversation ownership, explicit coverage, and atomic replacement.
Changing those invariants requires an ADR amendment or replacement.

## Consequences

- Long conversations reuse durable summaries without repeatedly processing the
  same complete turns.
- Explicit lineage requires more storage than one mutable text field.
- Late successful retries remain discoverable after a summary checkpoint.
- Model switching may create a summary-only compaction version.
- Summary failure cannot corrupt the last known-good version.

## Alternatives considered

- Store one mutable summary on the conversation — not selected because it loses
  version provenance and failure recovery.
- Treat a timestamp checkpoint as complete provenance — not selected because a
  retry can complete after that checkpoint.
- Rebuild a summary from all historical messages — not selected because it
  repeatedly processes covered content and can include incomplete turns.
- Share summaries across conversations — not selected because summaries contain
  conversation-specific history rather than Chat-wide user facts.

## Behavioral examples

- When context crosses the trigger, Chat summarizes the oldest complete turns,
  persists their attempt identifiers, and retains two recent turns.
- A failed response contributes nothing. If its later retry completes after a
  summary update, its attempt remains uncovered and can enter a future version.
- If summary generation fails, the prior version stays active and context
  proceeds only when ADR 017's mandatory components still fit.
- Switching to a smaller model may compact the active summary while preserving
  exactly the same effective source coverage.
