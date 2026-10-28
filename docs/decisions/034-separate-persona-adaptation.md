# ADR 034: Separate persona adaptation from memory and current state

- Status: Accepted
- Date: 2026-10-28
- Scope: Characters, Stage 7
- Refines: ADRs 006, 007, 010, and 026
- Consistent with: ADR 031

## Context

Conversation may change how a persona behaves toward one identity. That durable
adaptation must not rewrite the authored persona core, duplicate factual memory,
or turn temporary scene state into a lasting trait.

## Decision

Keep these continuity-owned concepts distinct:

- **Relationship state** describes the durable relationship between identity and
  persona, as defined by ADR 010.
- **Persona adaptation** describes durable continuity-specific behavior toward the
  identity, such as communication, openness, support, conflict, and shared-habit
  preferences. It may specialize expression of the persona core but cannot
  contradict or modify it.
- **Memory** records declarative facts and past events: what the persona can
  recall. Factual knowledge never substitutes for adaptation.
- **Current state** is temporary mood, scene, activity, or immediate context.
  Prompt inclusion alone does not make it durable.

One source turn may support both memory and adaptation, but each has independent
proposal, validation, persistence, correction, and context-eligibility rules.
Persona adaptation and memory remain isolated to their owning continuity.

## Consequences

- Remembering that the identity dislikes crowds is memory; choosing quieter
  invitations is adaptation only when evidence supports that behavior and it fits
  the persona core.
- A fresh continuity copies no prior memory, relationship projection, or persona
  adaptation; it receives its own user-selected starting relationship.
- Persona duplication continues to copy only the authored core.

## Alternatives considered

- Store adaptation as memory — rejected because recalling a fact and changing
  behavior are different context responsibilities and correction workflows.
- Evolve the persona core — rejected because the authored persona must remain stable
  across continuities.

