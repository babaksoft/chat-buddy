# ADR 009: Preserve immutable conversation branches and retry alternatives

- Status: Accepted
- Date: 2026-09-09
- Scope: Characters area; the former Chat mode is renamed Ongoing by ADR 013

## Context

Users need to explore alternate paths and regenerate a persona reply without
destructively rewriting prior conversation history.

## Decision

Model messages as immutable nodes with parent-message relationships. Maintain a
selected branch for each conversation; only that path contributes to model
context, memory extraction, and relationship evolution. Retrying the last
persona response creates an alternate response to the same user message, with a
visible, limited retry allowance of three retries per persona turn.

The graph has an implicit root. Persisted root children are user messages, roles
alternate on every edge, and every parent shares the child's complete ownership
scope. Parent traversal is the only path ordering; sequence and cached depth are
not persisted. Reads of the selected ancestry are separate from inspection of all
nodes and alternatives.

Selection and branch mutations compare the caller's expected selected leaf before
committing. Retrying applies only to the selected path's last completed persona
response. Only successful persona siblings consume the allowance; failed and
interrupted attempts remain evidence outside committed history. Selecting an
alternative or saved future always names its exact node.

Summaries are immutable branch-addressable lineages. Each revision identifies its
predecessor and persona-message checkpoint. The current summary is the deepest
compatible checkpoint on the selected ancestry, not a conversation-wide active
row. Persona messages copy the effective response generation and budget, fixed
response-style snapshot, configured evolution-strategy identity, and completing
attempt identifier.

Mode policy is fail closed. Ongoing and a latest Storyline scene branch in place,
as does an open Timeline day. An older Storyline scene with dependent later scenes
and a closed Timeline day return a fork-required decision. Missing or contradictory
mode facts also require a fork; persistence for those forks belongs to the stages
that introduce Storylines and Timelines.

## Consequences

- Prior paths remain recoverable rather than being overwritten.
- Services must preserve the selected path when assembling context or deriving
  downstream state.
- Mode-specific branching rules apply: Chat branches in place; the latest
  Storyline scene branches in place while an older changed scene forks its
  Storyline; an open Timeline day branches in place while a closed day requires
  a Timeline fork.

## Alternatives considered

- Overwrite a message when retrying — not selected because it loses a recoverable
  alternative and obscures the history used to derive state.
- Include every branch in context — not selected because mutually exclusive paths
  would contaminate the active conversation.

## Behavioral examples

- Selecting a retry alternative changes future context and extraction; the
  unselected alternative remains stored but has no downstream effect.
- Branching an older Storyline scene with later scenes preserves the old future
  by creating a separate Storyline continuity.
