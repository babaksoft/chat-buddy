# ADR 033: Treat Storyline forks as branch-from-here

- Status: Accepted
- Date: 2026-10-26
- Scope: Characters
- Refines: ADRs 009, 025, and 028

## Context

A Storyline fork represents an alternate future from a persona response in an
older scene. Treating retry and saved-future selection as additional fork modes
adds action-specific rules without changing the structural copy.

## Decision

Only Branch from here creates a continuity fork. It names any exact owned persona
message, whether or not that message belongs to the currently selected path and
whether or not it has descendants.

In a writable conversation, branching selects the named message as the next-send
branch point without deleting saved nodes. In an older Storyline scene with later
scenes, the same operation creates a distinct Storyline and copies earlier selected
scene histories plus the chosen scene's ancestry through that branch point. Retry
and saved-future selection remain ordinary writable-scene operations and never
create a fork.

The reviewed fork contract records the branch point, source guards, target profile
pair, and new Storyline name. It does not carry a generic graph-action discriminator.

## Consequences

- Selected-path and off-path persona messages use one branching workflow.
- Historical retry and selection are unavailable rather than alternate fork modes.
- Fork copying, identifier remapping, idempotency, and source isolation remain
  unchanged.
