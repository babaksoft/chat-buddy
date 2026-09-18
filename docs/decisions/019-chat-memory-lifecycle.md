# ADR 019: Store provenance-aware, user-controlled Chat memory

- Status: Accepted
- Date: 2026-09-18
- Last revised: 2026-09-19
- Refines: ADR 013

## Context

The Chat prototype stores one globally unique key/value row per memory. It has no
source provenance, history, lifecycle beyond physical deletion, or distinction
between automatic inference and user correction.

Stage 3 redesigns and supersedes that prototype. The previous schema is a useful
starting point, but its rows were test data and have already been deleted. The
new memory model has no legacy-data preservation or conversion requirement.

Chat memory must be reusable across Chat conversations while remaining isolated
from Characters. Users must be able to inspect, correct, exclude, reactivate,
and permanently delete it.

## Decision

Represent a Chat memory as a logical fact with a stable identifier and normalized
subject. It has one current revision and may retain superseded revisions. A
revision records interpreted content, lifecycle state, timestamps, and origin.
Subjects identify conflicts; they are not unqualified database keys and are not
globally unique across historical revisions.

Persisted revision states are `active`, `excluded`, and `superseded`. Only the
current active revision is eligible under ADR 017. Exclusion is reversible and
retains content and provenance for inspection. Reactivation changes the current
revision from excluded to active. Replacing a revision atomically supersedes the
old revision.

`deleted` is a terminal domain result, not a retained database tombstone. Hard
deletion purges the logical memory's complete revision lineage and provenance in
one transaction. ADR 020's attempt-level processing receipt contains no memory
content and is not part of a logical memory lineage. A later conversation may
extract the same fact again because deletion leaves no suppression tombstone.

Memory origins are:

- `extracted`, with the source conversation, source user message, source
  assistant message, and completed generation attempt under ADR 020; and
- `user_correction`, with the superseded revision and correction time.

A user correction may change the subject and content of an active memory. It
creates a user-correction revision in the same lineage and supersedes the former
revision. A normalized subject that conflicts with another current logical
memory is rejected rather than merging lineages implicitly. An excluded memory
must be reactivated before correction, so correction cannot silently defeat
exclusion.

Memory is Chat-wide. Every current active revision is eligible in every Chat
conversation, subject to ADR 017's budget, but no Chat memory is visible to
Characters.

Deleting a source conversation does not silently delete Chat-wide memory. The
extracted origin is marked as having an unavailable source, its source foreign-
key references are cleared, and the UI reports that the source is unavailable.
Conversation-deletion confirmation states that Chat memory is managed separately.
Hard-deleting the memory removes the remaining statement and origin.

The Stage 3 migration may alter or replace the empty prototype memory table. It
does not convert, backfill, or preserve prototype rows. Applied baseline and
Stage 2 migration files remain unchanged; the redesign uses a new Chat migration.

Additive metadata and stronger validation are compatible updates when they
preserve Chat-wide ownership, user authority, provenance meaning, and deletion
semantics. Changing those invariants requires an ADR amendment or replacement.

## Consequences

- Users can distinguish extracted facts from their own corrections.
- Corrections and exclusions outrank automatic extraction.
- Superseded revisions make changes inspectable and attributable.
- Hard deletion retains no memory tombstone or provenance.
- Conversation deletion and Chat-wide memory deletion remain separate actions.
- The empty prototype schema can be reshaped without carrying temporary data
  concepts into the final model.

## Alternatives considered

- Extend the unique key/value row in place — not selected because it cannot
  represent revision history and provenance cleanly.
- Store only the latest content — not selected because correction and automatic
  replacement would become indistinguishable.
- Retain deletion tombstones — not selected because permanent deletion must
  remove user content and provenance.
- Delete memory with its source conversation — not selected because memory is
  deliberately Chat-wide and separately controlled.
- Preserve prototype rows — not selected because they were disposable test data,
  are already deleted, and are not part of the redesigned contract.

## Behavioral examples

- Correcting an active extracted memory creates a user-correction revision and
  supersedes the extracted revision.
- Excluding a memory removes it from the next prompt in every Chat conversation;
  reactivation makes the same current revision eligible again.
- Hard deletion removes the logical memory, all revisions, and all provenance.
- Deleting the source conversation leaves the memory active but marks its source
  unavailable until the memory is separately deleted.
