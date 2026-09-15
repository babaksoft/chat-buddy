# ADR 012: Preserve legacy data in archived default continuities

- Status: Superseded by ADR 013
- Date: 2026-09-09
- Superseded: 2026-09-15

## Context

The existing application has conversations and global memories that predate the
identity, persona, continuity, branch, and scoped-memory model. The migration
must retain user data without silently applying legacy information to a new
relationship.

## Decision

Import existing conversations under default identity and persona data as archived
legacy Chat continuities. Preserve global memories for user review, but do not
silently inject them into newly created continuities. Verify the migration
against populated PostgreSQL data before release.

## Consequences

- Existing history remains accessible after the schema transition.
- New continuities start without unreviewed legacy memory in their context.
- The Alembic migration requires explicit data mapping and a populated-database
  verification path.

## Alternatives considered

- Delete or discard legacy data — not selected because it would destroy user
  history.
- Automatically assign global memories to every new continuity — not selected
  because it violates continuity isolation and can reveal irrelevant information.

## Behavioral examples

- A pre-migration conversation appears under the imported default identity and
  persona as an archived legacy Chat continuity.
- A preserved global memory is visible for review but cannot influence a new
  Storyline or Timeline unless a future explicit transfer feature adds it.
