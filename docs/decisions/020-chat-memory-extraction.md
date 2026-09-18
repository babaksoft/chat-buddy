# ADR 020: Extract Chat memory with bounded completed-turn processing

- Status: Accepted
- Date: 2026-09-18
- Last revised: 2026-09-19
- Refines: ADRs 016 and 019

## Context

The Chat prototype runs memory extraction after response completion but passes a
message list captured before the assistant response was committed. It extracts
periodically from broad history and upserts unqualified keys. This does not
provide exact source provenance.

Chat needs useful memory extraction without introducing a repair queue, an
indefinitely retryable side-effect lifecycle, or detailed effect bookkeeping.
Extraction is helpful but remains subordinate to delivery of the assistant
response.

## Decision

Use a dedicated completed-turn memory-extraction service. Invoke it only after
the assistant message and completed generation attempt commit. Pass the exact
source user message and assistant message together with their conversation and
attempt identifiers. Pending, streaming, failed, and interrupted attempts never
trigger extraction.

The assistant message establishes that the turn completed and supplies
conversational evidence. Extraction prompts treat user-provided facts as
authoritative and must not turn an unsupported assistant assertion into user
memory.

Processing is bounded and synchronous with the post-completion application flow.
The service makes at most a configured positive number of processing attempts;
the initial limit is three. Each processing attempt invokes the utility provider,
parses and normalizes its candidates, and applies the complete candidate set in
one repository transaction. A utility, parsing, validation, or transaction
failure rolls back candidate effects and consumes one attempt. After exhaustion,
the service records an `exhausted` outcome, logs safe diagnostics, and gives up.
There is no scheduled, background, or later automatic repair.

A minimal processing receipt keyed by completed generation attempt records either
`succeeded` or `exhausted`, its attempt count, and completion time. A successful
empty candidate set is still `succeeded`. Candidate changes and a successful
receipt commit atomically. An exhausted receipt contains no candidate content or
provider payload. A repeated callback sees either terminal receipt and does not
invoke the utility provider again. No per-memory extraction-effect association
is stored.

Normalize candidate subjects and content before comparison. For a candidate and
an existing current revision with the same subject:

- identical normalized content creates no revision;
- different extracted content creates a new extracted revision and atomically
  supersedes the current extracted revision;
- a current user-correction revision is never automatically overwritten; and
- an excluded revision is neither replaced nor reactivated.

A successful response retry under ADR 016 has one completed attempt and one exact
completed turn. Only that completed attempt is eligible for extraction. Earlier
failed attempts and partial output produce no candidates or receipts.

Extraction failure never rolls back the assistant message, changes the completed
attempt state, or becomes user-blocking response failure.

## Consequences

- Every extracted memory revision has exact committed source provenance.
- Extraction consumes bounded time and cannot become ongoing recoverable work.
- Repeated callbacks invoke neither the utility provider nor memory persistence.
- A small terminal receipt supports idempotency without effect-level bookkeeping.
- User correction and exclusion remain authoritative over later inference.
- An exhausted extraction may permanently miss memories from that turn; this is
  an accepted tradeoff for simple best-effort Chat behavior.

## Alternatives considered

- Extract from the whole conversation periodically — not selected because source
  attribution becomes ambiguous.
- Extract before committing the assistant response — not selected because an
  incomplete turn could create durable memory.
- Leave failed extraction retryable on later callbacks — not selected because it
  creates open-ended side-effect recovery state.
- Add a background repair worker — not selected because Chat does not need that
  operational complexity.
- Persist effect associations for every candidate — not selected because memory
  revision provenance and a terminal attempt receipt provide the required facts.
- Let a new candidate overwrite user-controlled memory — not selected because
  automatic inference must not override explicit correction or exclusion.

## Behavioral examples

- A completed turn succeeds on its second extraction attempt and stores one
  `succeeded` receipt with an attempt count of two.
- Three extraction failures store one `exhausted` receipt; the assistant response
  remains completed and later callbacks do nothing.
- A stream that emits partial text and fails creates no memory or extraction
  receipt.
- A successful response retry is processed using its edited user content when
  applicable and its newly committed assistant message.
- A conflicting candidate supersedes an extracted revision but is ignored when
  the current revision is user-corrected or excluded.
