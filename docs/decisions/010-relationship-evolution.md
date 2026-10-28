# ADR 010: Evolve relationships conservatively with explicit milestones

- Status: Accepted
- Date: 2026-09-09
- Last revised: 2026-10-28
- Scope: Characters
- Refines: ADRs 006–009
- Refined by: ADRs 034–036

## Context

Relationship behavior must be believable, controllable, and explainable without
reducing an identity/persona relationship to one score.

## Decision

Store qualitative relationship state per identity, persona, and continuity. It
separates social status, romantic status, current interaction dynamic, trust,
affection, and provenance-backed milestones. Friendship and romance are
independent tracks; supporting dimensions imply neither a status nor an event.

User-selected relationship intent and boundaries constrain evolution rather than
acting as inferred dimensions. Automated evolution cannot remove or weaken a
boundary. Platonic intent prohibits romantic evolution; other intent may permit
it but never supplies evidence for it.

Major romantic transitions require explicit, unambiguous narrative evidence.
Partnership, engagement, marriage, breakup, and reconciliation cannot result from
vague sentiment. The baseline permits a current dynamic to change after one strong
explicit exchange, while trust, affection, and social status require compatible
evidence from at least two distinct turns. Reversal uses the same conservative
threshold, and temporary conflict changes the dynamic before durable status.

[ADR 034](034-separate-persona-adaptation.md) separates relationship state,
persona adaptation, memory, and current state. [ADR 035](035-use-replayable-evolution-events.md)
defines validated proposals, append-only events, corrections, and rebuildable
projections. [ADR 036](036-version-evolution-experiments.md) separates stable
invariants from versioned experimental policy and owns the initial evaluation
scenario inventory.

## Consequences

- Close friendship does not imply romance, and temporary conflict does not erase
  an established status.
- An established starting relationship is recorded as user-selected state without
  inventing shared events or history.
- The UI presents qualitative state and provenance rather than progress bars or
  hidden relationship scores.

## Alternatives considered

- Use one numeric relationship score — rejected because it cannot express
  independent friendship, romance, dynamics, and evidence.
- Treat boundaries as inferred relationship state — rejected because boundaries
  remain under user control.
