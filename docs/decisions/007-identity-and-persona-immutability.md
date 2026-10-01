# ADR 007: Freeze identities and persona cores at first continuity use

- Status: Accepted
- Date: 2026-09-09
- Scope: Characters area

## Context

Authored changes must not reinterpret established relationships or affect other
continuities. Authors should be able to correct unused profiles.

## Decision

Identities and persona cores are editable until their first continuity is
successfully created, then all authored fields, including display fields, are
permanently frozen. A persona freezes globally on first use with any identity.
Selection, drafts, canceled starts, and failed starts do not newly freeze profiles.
Archival never unfreezes them.

A continuity cannot switch identity or persona. Confirmation must use the profile
content reviewed by the user; intervening edits require renewed review.

After first use, authored changes require a new or duplicated profile. Duplicates
are editable and copy only authored fields, without history or relationship state.
Conversation-driven adaptation belongs only to its continuity.

## Consequences

- Authors can correct newly created profiles without duplication.
- Existing and unrelated continuities retain their meaning.
- A persona used by one identity cannot subsequently be edited for another.

## Alternatives considered

- Freeze personas at creation: prevents simple corrections before use.
- Allow edits after use: risks rewriting established relationships.
