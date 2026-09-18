# ADR 020: Extract Chat memory only from completed turns

- Status: Accepted
- Date: 2026-09-18
- Refines: ADRs 016 and 019

## Context

The Chat prototype runs memory extraction after response completion but passes a
message list captured before the assistant response was committed. It extracts
periodically from broad history and upserts unqualified keys. This does not
provide exact source provenance and makes repeated side-effect execution
ambiguous.

ADR 016 requires memory extraction and other completed-turn effects to run only
after the generation attempt and assistant message commit. ADR 019 requires an
extracted revision to identify that exact source.

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

Extraction processing is idempotent by completed attempt identifier, including
when the extractor returns no candidates. Repeating post-completion processing
does not invoke the utility provider again after a successful processing record.
A failed extraction remains unprocessed and may be retried by later synchronous
completed-turn processing. It never rolls back or changes the completed response,
and Stage 3 introduces no scheduled repair worker.

Normalize candidate subjects and content before comparison. For a candidate and
an existing current revision with the same subject:

- identical normalized content creates no revision;
- different extracted content creates a new extracted revision and atomically
  supersedes the current extracted revision;
- a current user-correction revision is never automatically overwritten; and
- an excluded revision is neither replaced nor reactivated.

A successful retry under ADR 016 is a distinct completed attempt and may be
processed once. Its reused source user message is not duplicated. Failed attempts
and earlier partial output produce no candidates or observations.

Utility-prompt, parsing, and validation improvements are compatible updates when
they preserve completed-turn timing, attempt idempotency, source provenance, and
user authority. Changing those invariants requires an ADR amendment or
replacement.

## Consequences

- Every extracted memory revision has exact, committed source provenance.
- Repeated callbacks cannot duplicate memory effects or utility calls.
- Extraction failure cannot invalidate a completed assistant response.
- User correction and exclusion remain authoritative over later inference.
- Processing every eligible completed turn replaces the prototype's periodic
  broad-history extraction.

## Alternatives considered

- Extract from the whole conversation periodically — not selected because source
  attribution and idempotency become ambiguous.
- Extract before committing the assistant response — not selected because an
  incomplete turn could create durable memory.
- Retry extraction in a background worker — deferred because Stage 3 needs no
  new worker infrastructure.
- Let a new candidate overwrite any current revision — not selected because
  automatic inference must not override explicit user control.

## Behavioral examples

- A completed turn is processed once even if its post-completion callback runs
  repeatedly.
- A stream that emits partial text and fails creates no memory.
- A successful retry is processed once using the original user message and its
  newly committed assistant message.
- A conflicting candidate supersedes an extracted revision but is ignored when
  the current revision is user-corrected or excluded.
