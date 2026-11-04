# ADR 040: Use Continuity Entries for shared Scene and Day structure

- Status: Accepted
- Date: 2026-11-04
- Scope: Characters, Stage 8
- Refines: ADRs 006, 008, 009, 011, 025, 031, 032, and 034–039

## Context

Storyline Scenes and Timeline Days differ in product behavior, but both identify
one ordered, continuity-owned conversation. Keeping those shared facts separately
on Scene and Day has produced parallel positions, optional Scene/Day identifiers,
and Storyline-first names in memory and evolution contracts.

The shared structure needs one identity without turning authored Scene behavior or
Timeline calendar behavior into a generic abstraction. Ongoing must also retain
its distinct single-conversation shape.

## Decision

Define **Continuity Entry** as Characters architecture vocabulary for the shared
parent represented by either a Storyline Scene or a Timeline Day. Product flows
and user-facing text continue to say **Scene** and **Day**.

An immutable `ContinuityEntry` owns its stable identifier, continuity, identity,
persona, conversation, permanent Storyline or Timeline mode, and positive
immutable position within that continuity. `Scene` and `TimelineDay` contain that
Entry; they do not inherit from it or duplicate its fields.

Scene retains its title, setup, setup lock, and append rules, including the
Storyline revision guard, navigation, and fork behavior. Timeline Day retains its
local date, boundary timezone, UTC boundaries, closure observation, settled
selected leaf, calendar rules, and historical write guards. Entry does not own
summaries, transcripts, response-style settings, or derived state; those remain
owned through the exact Entry conversation or continuity according to their
existing contracts.

Ongoing has no Entry. Its sole conversation remains directly owned by its
continuity. A Storyline or Timeline conversation target requires exactly one
Entry, whose ownership and mode must match the target. Mode-specific services may
then resolve the corresponding Scene or Day details and fail closed on a subtype
mismatch.

Use one immutable `EntryPosition` containing the Entry identifier, continuity
identifier, mode, and positive position wherever shared temporal provenance is
needed. Positions are comparable only within the same continuity and mode.
Selected graph ancestry remains a separate eligibility dimension: Entry position
establishes temporal order, while the exact selected persona checkpoint proves
branch compatibility. Sharing an Entry never makes off-branch evidence eligible.

Memory evidence records exact source, occurrence, and learned Entry positions.
The learned Entry is the source Entry, and occurrence cannot be later than
learning. Entry-backed evolution evidence records its exact Entry position and
message checkpoint. Ongoing evolution evidence uses a distinct entryless shape;
it is not represented by nullable Entry data.

Persist Entries in one parent table. Scene and Timeline Day detail tables use the
Entry identifier as their one-to-one key. Each detail table carries a constrained
fixed mode discriminator and a composite foreign key to the parent Entry's
identifier and mode, so a Scene can reference only a Storyline Entry and a Day can
reference only a Timeline Entry. Memory and Entry-backed evolution provenance
reference the parent directly. This avoids polymorphic foreign keys while keeping
common ownership facts in one place.

## Consequences

- Shared contracts use `entry_id` and `EntryPosition`, never paired optional
  Scene/Day identifiers or parallel position types.
- Scene and Day repositories retain subtype behavior; a read-only Entry repository
  provides exact owned lookup and ordered continuity listing.
- Memory becomes mode-neutral Continuity memory, while Storyline and Timeline keep
  explicit context adapters for their different transcript and calendar policies.
- Evolution can share Entry-backed provenance without enabling Timeline evolution
  before its planned delivery slice.
- Database constraints can validate continuity, conversation, mode, and subtype
  ownership without inspecting serialized provenance.

## Alternatives considered

- Make Scene and Day inherit from Entry — rejected because inheritance encourages
  subtype objects to duplicate or override parent ownership and persistence facts.
- Keep a Scene/Day union in every shared contract — rejected because it preserves
  paired nullable fields and repeated mode dispatch.
- Put setup, calendar, summary, and transcript data on Entry — rejected because
  those facts do not have one shared meaning or lifecycle.
- Give Ongoing a synthetic Entry — rejected because its continuity already owns
  exactly one conversation and has no ordered Scene/Day boundary.
