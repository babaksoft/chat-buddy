# ADR 031: Keep Storyline memory temporal and user-controlled

- Status: Accepted
- Date: 2026-10-24
- Scope: Characters, Stage 6
- Refines: ADRs 006 and 008
- Consistent with: ADR 025

## Context

Storyline memory must remain inside its one continuity, respect scene order and
selected branches, and preserve user authority over extracted interpretations.

## Decision

A Storyline memory is a logical fact with a stable identifier and immutable
revision lineage. Exactly one revision is current and `active` or `excluded`;
older revisions are `superseded`.

Extraction creates an active extracted revision. Reinforcement adds distinct
evidence without changing content or authorship. An unambiguous extraction change
may supersede only an active extracted revision. User correction may change the
subject and content of an active revision and creates a user-authored active
revision. Exclusion and reactivation each create a revision while retaining
content, authorship, source, and temporal provenance. An excluded memory must be
reactivated before correction. Hard deletion removes the complete lineage,
evidence, and associated conflicts without a tombstone.

Management commands name the expected current revision. Stale or illegal changes
are rejected; repeated hard deletion reports absence. Automatic extraction cannot
reinforce or supersede an excluded revision or supersede user-authored content. It
may reinforce unchanged active user-authored content or record a conflict.

A conflict retains proposed content, exact evidence, target when present, and the
observed current revision. It starts unresolved. Explicit dismissal against the
expected current revision is its only transition and keeps the current memory.
Conflict content never becomes prompt-eligible memory. A repeated dismissal
against unchanged memory reports that it is already dismissed; a changed current
revision makes the command stale.

Every extracted revision and reinforcement identifies its continuity, scene,
complete selected source turn and persona checkpoint, extraction configuration,
and creation time. Occurrence position is the scene where the asserted event or
state occurred. Learned position is the source scene where the persona learned it;
occurrence cannot be later than learned.

A memory is eligible only when it belongs to the Storyline, its current revision
is active, its current-content source checkpoint is on the selected ancestry, and
both temporal positions are no later than the target scene. Switching away from a
source branch makes the memory ineligible without deleting it; switching back
restores eligibility. A deselected reinforcement does not invalidate content whose
originating evidence remains selected.

User correction retains the corrected revision's source and temporal positions
while recording authorship, time, and the superseded revision. A subject collision
with another current logical memory is rejected.

An ADR 025 fork copies only eligible active lineages whose originating evidence is
on copied paths. It assigns new target-continuity identifiers, remaps provenance,
and copies only supporting evidence whose source was copied. No continuity-owned
row is shared. Excluded or future memory and unresolved conflicts are not copied.

Stage 6 provides no source-record deletion. Any future deletion must reject a
scene, conversation, or message while memory provenance refers to it.

## Consequences

- Earlier scenes cannot see knowledge learned later.
- Branch changes affect eligibility without destructive memory rewrites.
- One profile pair has one active Storyline memory boundary; archived boundaries
  remain separately inspectable and never enter the replacement Storyline.

## Alternatives considered

- Admit all continuity memory regardless of scene — rejected because earlier
  scenes would see knowledge learned in their future.
- Mutate one current row in place — rejected because correction, extraction, and
  branch provenance would no longer be explainable.
