# ADR 009: Preserve immutable conversation branches and retry alternatives

- Status: Accepted
- Date: 2026-09-09

## Context

Users need to explore alternate paths and regenerate a persona reply without
destructively rewriting prior conversation history.

## Decision

Model messages as immutable nodes with parent-message relationships. Maintain a
selected branch for each conversation; only that path contributes to model
context, memory extraction, and relationship evolution. Retrying the last
persona response creates an alternate response to the same user message, with a
visible, limited retry allowance of three retries per persona turn.

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
