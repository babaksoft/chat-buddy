# ADR 026: Manage Characters personas as revisioned authored cores

- Status: Accepted
- Date: 2026-10-24
- Scope: Characters, Stage 4
- Refines: ADR 007

## Context

Personas are reusable across identities and continuities. Authors need to correct
unused definitions without letting later edits reinterpret an established
character or copy continuity-specific state into a new persona.

## Decision

A persona has a stable identifier and a global authored core containing its
display name, required definition, and optional long-term traits. Relationship
adaptation, current state, conversations, and continuity history are not part of
that core.

Creation produces revision 1 in an editable state. An edit replaces the complete
authored core under the same identifier, requires the revision observed by the
caller, and increments it. Stale, missing, and frozen edits are rejected
explicitly. Domain snapshots remain immutable, so an edit does not change a
previously observed value. Names need not be unique; lists use name and identifier
for deterministic order.

The first successful continuity start using a persona freezes every authored field
globally and atomically with that start, as required by ADR 007. Selection, review,
cancellation, and failed starts do not freeze it. Archiving every continuity does
not unfreeze it, and there is no in-place edit or unfreeze path after first use.

Duplication is the authored-change path for a frozen persona. It copies only the
authored core, optionally with revisions supplied by the author, into a new
identifier at revision 1. The duplicate is editable and carries no freeze state,
identity association, continuity, conversation, relationship state, adaptation,
or current state. The source remains unchanged.

## Consequences

- One persona has the same authored meaning in every continuity that uses it.
- Competing edits and starts cannot silently overwrite reviewed content.
- Duplicates are independent authored definitions rather than relationship clones.

## Alternatives considered

- Allow edits after first use — rejected because existing continuities would be
  silently reinterpreted.
- Copy continuity state when duplicating — rejected because that state belongs to
  its original continuity and identity relationship.
