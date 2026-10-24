# ADR 025: Use one active append-only Storyline per profile pair

- Status: Accepted
- Date: 2026-10-24
- Scope: Characters, Stage 6
- Refines: ADRs 006, 009, and 024
- Consistent with: ADR 013

## Context

Several Storylines for one identity/persona pair would make navigation and
continuity-scoped memory difficult to understand. Pre-creating and reordering
several empty scenes would also introduce state that has no conversation meaning.

## Decision

An identity/persona pair may own at most one active Storyline. The pair may
independently own an Ongoing continuity because the modes do not share conversation
or memory state.

Confirmed start atomically creates the named Storyline and one starting scene from
the reviewed profiles, starting relationship, scene title and setup, and fixed
response style. The confirmation is idempotent over every input. Starting another
Storyline for that pair is rejected while one is active.

Archival is explicit, permanent, and read-only. It releases the pair to start a
fresh Storyline through a new confirmation and starting relationship. The archived
Storyline retains its scenes and memory for inspection, but transfers neither into
the replacement. Profiles remain frozen. Any number of archived Storylines may
therefore exist for the pair, but only one is resumable.

Scenes form an immutable append order. The latest scene is the only normally
writable scene. A user may resume it or, after it has at least one complete
selected user/persona exchange and no unmatched input or open attempt, append and
enter one next scene. Appending captures that scene's title, setup, and fixed style
and leaves no second empty scene. Scenes cannot be created in batches, inserted,
reordered, or deleted. Their positions never change.

A scene setup freezes with its first committed user message. Its title remains
editable presentation metadata and never enters prompts. Stage 6 provides no
scene, conversation, or message deletion; archive is the non-destructive
Storyline lifecycle action.

The latest scene uses ADR 009's retry, selection, and in-place branch rules. An
action from an older scene with later scenes still requires a Storyline fork. A
fork must use a distinct identity/persona pair that has no Storyline. To preserve
the copied history's meaning, the reviewed fork creates that pair by duplicating
at least one source profile without authored changes and freezes newly duplicated
profiles when the fork commits. Revised profiles may start a new Storyline but
cannot receive copied history.

The fork copies selected scene histories and metadata only through the chosen
source point, retains the source starting relationship under a user-authored new
Storyline name, gives every owned record a new identifier, records source mappings,
and changes only the fork. It copies no later scene, unselected alternative, open
attempt, or unresolved conflict. Memory copying follows ADR 031.

This makes Storyline structurally similar to Timeline: both grow forward through
one ordered continuity. Storyline boundaries are user-authored named scenes that
may span days; Timeline boundaries are local dates and a day is created only when
an exchange occurs.

## Consequences

- Navigation presents one resumable Storyline and its memory boundary, with older
  archived Storylines clearly separated.
- At most one empty scene exists, and it is always the latest scene.
- Exploring an older Storyline future requires an explicit duplicate profile and
  a separately owned Storyline.

## Alternatives considered

- Allow several active Storylines per pair — rejected because their distinct
  memories make the current relationship scope unclear.
- Pre-create and reorder empty scenes — rejected because append order expresses
  narrative chronology without placeholder conversations.
