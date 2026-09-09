# ADR 010: Evolve relationships conservatively with explicit milestones

- Status: Accepted
- Date: 2026-09-09

## Context

Relationship behavior must be believable, controllable, and explainable without
reducing an identity/persona relationship to a single score.

## Decision

Store relationship state per identity, persona, and continuity. Represent social
status, romantic status, current dynamic, qualitative familiarity/trust/
affection, boundaries, and provenance-backed milestones. At continuity creation,
the user selects platonic, open to romance, established relationship, or let it
develop naturally. Model-generated proposals are validated by application and
domain rules before persistence. Major romantic milestones require an explicit
narrative event; gradual changes use conservative thresholds and hysteresis.

## Consequences

- Close friendship does not imply romance, and a temporary conflict does not
  erase an established status.
- The UI shows qualitative state and provenance, not progress bars or experience
  points.
- Users can correct relationship changes, and branch or continuity forks rebuild
  state from their valid history.

## Alternatives considered

- Use one numeric relationship score — not selected because it cannot express
  independent friendship, romance, dynamics, boundaries, and evidence.
- Persist model-generated changes directly — not selected because it bypasses
  user intent and domain transition safeguards.

## Behavioral examples

- A user may choose an established starting relationship, but the application
  records it as user-selected without inventing shared events or history.
- Partnership, engagement, marriage, breakup, and reconciliation cannot result
  from vague sentiment alone; each requires explicit narrative evidence.
