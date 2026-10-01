# ADR 023: Manage Characters identities with immutable snapshots and revisions

- Status: Accepted
- Date: 2026-10-01
- Scope: Characters, Stage 4 Slice 1

## Context

ADR 007 requires identities to freeze at first continuity use. Before that point,
concurrent edits must not silently overwrite each other. Default setup must be
safe across application sessions without depending on Chat initialization.

## Decision

Use frozen Pydantic authored values and snapshots, separate from SQLAlchemy
models. A snapshot carries a stable UUID, positive authored revision, permanent
freeze flag, and default designation. Full authored replacements require an
expected revision. The service checks edit eligibility; persistence repeats those
guards in a conditional update, increments the revision, and reports missing,
frozen, or stale identities through typed domain errors. Slice 3 will lock the
same identity row and verify that revision at continuity start.

Create the Characters default identity explicitly on Characters demand. Initially
it is named **You**, with all demographics unknown. A nullable unique database slot
reserves the default designation independently of its editable display name.
Concurrent insert conflicts return the committed winner. Duplicates copy only
validated authored details, optionally revised, and receive new identifiers,
revision 1, editable state, and no default designation or continuity history.

All authored fields are frozen after first use, including cosmetic fields, until
a later decision introduces a distinction. No unfreeze API is provided.

## Consequences

- Old snapshots remain unchanged after an edit; callers reload on stale revision.
- Database uniqueness, rather than process memory, enforces default setup.
- Optional demographics allow setup without fabricated facts; age and birth date
  remain alternative inputs, and timezone is optional for Ongoing.
- This slice supplies backend identity operations. Continuity-driven freezing and
  UI composition remain assigned to Slices 3 and 8.

## Alternatives considered

- Mutable domain values risk changing the meaning of already observed snapshots.
- Last-write-wins updates lose competing edits and cannot verify reviewed starts.
- A process-local default cache cannot enforce uniqueness across sessions.
