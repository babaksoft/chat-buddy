# ADR 007: Freeze identities at first use and keep persona cores immutable

- Status: Accepted
- Date: 2026-09-09

## Context

Identity details and persona traits affect the meaning of a conversation. Later
semantic edits must not silently reinterpret an established relationship or
change a persona for other users and continuities.

## Decision

An identity is editable until its first continuity begins, then it is frozen. A
continuity cannot switch identity after it begins. Persona cores are immutable;
editing a persona creates a duplicate persona. Conversation-driven adaptation is
stored only in the continuity.

## Consequences

- Starting a continuity transactionally locks the selected identity.
- Users create or duplicate an identity to change its semantic details after
  first use.
- Persona core edits cannot alter existing or unrelated continuities.

## Alternatives considered

- Allow semantic identity edits after first use — not selected because it can
  rewrite the meaning of an established relationship.
- Mutate the persona core from conversation outcomes — not selected because it
  would leak adaptation across continuities and identities.

## Behavioral examples

- An identity can be corrected before any continuity exists; after the first
  continuity starts, a different semantic identity requires a new or duplicated
  identity.
- A persona's learned preference in one continuity does not modify the persona
  selected in another continuity.
