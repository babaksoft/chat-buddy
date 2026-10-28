# ADR 035: Validate evolution into replayable events

- Status: Accepted
- Date: 2026-10-28
- Scope: Characters, Stage 7
- Refines: ADRs 009, 010, and 033
- Consistent with: ADRs 031 and 032

## Context

Model interpretation must not gain write authority. Evolution must remain
explainable after correction, retry selection, branching, and Storyline forks.

## Decision

Use these terms consistently:

- **Evidence** is an exact immutable eligible source turn or checkpoint from the
  continuity's selected history. Summaries may aid interpretation but cannot be
  final provenance.
- **Proposal** is a bounded atomic set of typed relationship or adaptation changes
  returned by a strategy. It is not durable state.
- **Decision** is the application's terminal result: apply, reject with a stable
  reason, or record no change.
- **Event** is an immutable accepted change, including a user-authored correction,
  with exact evidence or user provenance.
- **Effect** idempotently processes one source persona checkpoint and records its
  configuration and terminal decision.
- **Projection** is a rebuildable current relationship or adaptation view. It is a
  cache, not the source of truth.

After an eligible completed selected turn, a strategy may propose changes. The
application validates ownership, evidence, expected projection revision, intent,
boundaries, persona-core compatibility, transitions, thresholds, and proposal
bounds. It applies the proposal atomically or rejects it in full. Archived
continuities cannot evolve.

Accepted changes are append-only events. A correction appends a user-authored
event that excludes or replaces an interpretation without editing its source or
original event. Projections replay from the user-selected starting state and
currently eligible events.

Branch selection makes events supported only by deselected evidence inactive and
restores them when that evidence is selected again. A reviewed Storyline fork
copies only events supported by copied history, remaps ownership and provenance,
and evolves independently. A fresh continuity copies no events or projections.

## Consequences

- Reprocessing one source checkpoint cannot duplicate events.
- Deleting a projection and replaying eligible events produces the same state.
- Corrections and branch changes remain explainable without destructive history
  edits.

## Alternatives considered

- Persist strategy output directly — rejected because it bypasses validation and
  user authority.
- Mutate the current projection in place — rejected because replay, correction,
  and branch eligibility would be lost.

