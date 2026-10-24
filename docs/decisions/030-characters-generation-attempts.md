# ADR 030: Persist recoverable Characters response attempts

- Status: Accepted
- Date: 2026-10-24
- Scope: Characters, Stages 4–5
- Refines: ADRs 014 and 024
- Consistent with: ADRs 009 and 028

## Context

Persona responses stream outside database transactions. Failure, cancellation,
process loss, or archival can occur after user input is accepted but before a
complete persona message exists. Partial output must remain recoverable evidence
without becoming conversation history or downstream source material.

## Decision

Represent every Characters response invocation as a durable attempt with
`pending`, `streaming`, `completed`, `failed`, and `interrupted` states. It records
the complete conversation ownership, source user message, submitted input,
effective response generation, incomplete output, and lifecycle times. Effective
generation and submitted input are immutable after reservation.

A conversation has at most one pending or streaming attempt and at most one
unmatched user tail. Starting a turn atomically creates its user node and pending
attempt. Successful completion atomically creates one persona node and marks the
attempt completed. Only that persona node enters selected history, context,
summaries, or later derivation.

Failure and interruption are terminal for an individual attempt. Their partial
output remains attempt evidence and is never promoted to a persona node. Continuing
an incomplete turn creates a new attempt for the existing unmatched user node; it
does not duplicate the input or rewrite prior attempts. Resume reconciles an
abandoned open attempt before another action proceeds.

Provider streaming occurs outside transactions. Reservation and completion both
require full ownership and an active continuity. Completion rechecks the attempt's
guarded conversation state so archival or a Stage 5 selection change fences late
output. Current conversation settings affect only future attempts; each completed
persona node retains its own effective generation, response-style, strategy, and
completing-attempt provenance.

Completed-response alternatives use ADR 028's separate retry operation and bounded
allowance. Incomplete continuation never consumes that allowance.

## Consequences

- Restart and provider failure preserve a truthful, actionable unmatched turn.
- Partial output cannot contaminate prompts, summaries, or derived state.
- Historical persona responses remain reproducible after configuration changes.

## Alternatives considered

- Persist streaming text directly as a persona message — rejected because partial
  output could be mistaken for a completed response.
- Add another user node for continuation — rejected because it duplicates one
  intent and breaks user/persona turn structure.
