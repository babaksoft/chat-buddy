# ADR 006: Make continuity the boundary for relationship state

- Status: Accepted
- Date: 2026-09-09
- Last revised: 2026-11-02
- Scope: Characters area; terminology and ownership clarified by ADR 013

## Context

Chat Buddy supports multiple identities, personas, and modes. The application
needs unambiguous ownership and terminology so information cannot leak between
separate versions of a relationship.

## Decision

Define a continuity as one coherent identity/persona relationship. A continuity
owns its mode, conversations, eligible memories, relationship state, and persona
adaptation. Information never crosses continuities unless an accepted workflow
makes the transfer explicit to the user.

Storyline forks are the only history-copying workflow currently accepted. They
create distinct continuities and remap copied ownership and provenance under ADRs
025 and 033; they never make one record belong to two continuities. Timeline does
not copy history or create continuity forks under ADR 039.

## Consequences

- Identity and persona are global definitions; relationship-specific information
  is continuity-scoped.
- A continuity has exactly one mode: Ongoing, Storyline, or Timeline.
- Context assembly and persistence queries must use the current continuity as a
  mandatory isolation boundary.

## Alternatives considered

- Scope memories and relationship state only to an identity/persona pair — not
  selected because distinct Ongoing, Storyline, and Timeline continuities need
  separate histories.
- Use a single global relationship state per persona — not selected because it
  would expose one identity's interaction history to another.

## Behavioral examples

- Two continuities for the same identity and persona do not share memories,
  adaptation, or relationship state.
- A memory transfer between continuities requires an explicit user action; it is
  never an implicit context-building behavior.
