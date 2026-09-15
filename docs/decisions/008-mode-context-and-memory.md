# ADR 008: Apply mode-specific context and memory eligibility

- Status: Accepted
- Date: 2026-09-09
- Scope: Characters area; the former Chat mode is renamed Ongoing by ADR 013

## Context

Chat, Storyline, and Timeline have different temporal and narrative semantics.
Using one global memory policy would reveal future or unrelated knowledge to the
model.

## Decision

Assemble model context in this stable order: persona core, identity, relationship
intent and state, eligible memories, scene setup and current state, response
style, then conversation summary and recent selected-branch messages. Keep Chat
free of extracted long-term memory; use its rolling summary only for context
compression. Extract Storyline and Timeline memories after complete turns, and
admit only active, in-scope, temporally eligible memories from the selected
branch or its applicable ancestors.

## Consequences

- Token budgeting and summarization remain separate from memory eligibility.
- A Storyline scene can use its own and earlier scenes' eligible memories, never
  memories from later scenes.
- A Timeline uses current-day messages as short-term context and eligible prior
  memory and relationship state as long-term context.

## Alternatives considered

- Inject all stored memories into every prompt — not selected because it leaks
  information across continuities, branches, and time.
- Extract long-term memory for Chat — not selected because Chat's relationship
  development and compression remain local to that chat continuity.

## Behavioral examples

- A later Storyline scene can learn from an earlier scene, but an earlier scene
  cannot see information learned later in that Storyline.
- Excluded, superseded, or deleted memories are not eligible for model context.
