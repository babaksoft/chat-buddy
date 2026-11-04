# Stage 8 Structural Refactor Plan — Continuity Entries

Status: In progress

Last updated: 2026-11-04

## Outcome

Introduce **Continuity Entry** as the shared structural concept represented by a
Storyline Scene or a Timeline Day, then rebuild the shared memory and evolution
boundaries around that concept before Stage 8 Slice 10 adds Timeline evolution.

The refactor removes the accidental Storyline-first vocabulary and the parallel
Scene/Day fields introduced while Timeline memory was added. Shared contracts use
one required Entry reference. Scene and Timeline Day remain distinct domain
concepts wherever their behavior differs.

The intended shared structure is:

```text
Continuity
└── Continuity Entry
    ├── Storyline Scene details
    └── Timeline Day details

Continuity Memory
└── Memory Evidence
    ├── source Entry
    ├── occurrence Entry
    └── learned Entry

Evolution Effect
└── exact Ongoing turn or Entry-backed checkpoint
```

At completion:

- `ContinuityEntry` is the shared immutable owner of identity, persona,
  continuity, conversation, mode, and position for a Scene or Timeline Day.
- `EntryPosition` replaces `ScenePosition`, `DayPosition`, and `MemoryPosition`.
- Shared contracts use `entry_id`, never paired `scene_id` and `day_id` fields.
- Memory uses `ContinuityMemory`, `ContinuityMemoryRepository`,
  `DbContinuityMemoryRepository`, and `ContinuityMemoryService` without aliases.
- Memory source, occurrence, learned, and extraction-effect provenance use one
  required Entry reference.
- Entry-backed evolution evidence uses the same Entry identity and position.
- Ongoing evolution remains explicitly entryless through a genuinely distinct
  evidence shape.
- Timeline evolution remains unavailable until Slice 10; the refactor prepares
  its structural seams without delivering the feature early.
- Persistence uses `characters.continuity_entries` and
  `characters.continuity_memories`; no table or model retains a Storyline-only
  name for mode-neutral data.
- Chat schema objects, migrations, records, behavior, and runtime initialization
  remain unchanged.

## Terminology and ownership

Use the following vocabulary consistently in source, persistence, tests, ADRs,
and design documentation:

| Current concept | Refactored concept |
|---|---|
| Structural parent shared by Scene and Day | `ContinuityEntry` |
| `ScenePosition`, `DayPosition`, `MemoryPosition` | `EntryPosition` |
| Shared `scene_id` / `day_id` | `entry_id` |
| Memory occurrence Scene/Day | `occurrence_entry_id` |
| Memory learned Scene/Day | `learned_entry_id` |
| `StorylineMemory` and aliases | `ContinuityMemory` |
| `StorylineMemoryRepository` and aliases | `ContinuityMemoryRepository` |
| `DbStorylineMemoryRepository` and aliases | `DbContinuityMemoryRepository` |
| `StorylineMemoryService` / `TimelineMemoryService` | `ContinuityMemoryService` |
| `StorylineMemoryModel` | `ContinuityMemoryModel` |
| `storyline_memories` | `continuity_memories` |
| Storyline evolution checkpoint | Entry-backed evolution checkpoint |

`Entry` is architecture language, not replacement product language. User-facing
flows, UI labels, and mode-specific APIs continue to say **Scene** and **Day**.

The Entry boundary owns only facts shared by both subtypes:

- Stable Entry identifier.
- Permanent identity, persona, and continuity ownership.
- Exact owned conversation.
- Permanent continuity mode.
- Positive immutable position inside the continuity.

Scene retains title, setup, setup-locking, Scene revision, append policy, and
Storyline-specific navigation. Timeline Day retains local date, boundary timezone,
UTC opening and closing facts, closure observation, settled leaf, calendar policy,
and historical write guards.

An Entry position is meaningful only inside one continuity. Equal numeric
positions in different continuities or modes have no relationship.

## Design constraints

The refactor must preserve these properties:

- Ongoing has no Entry. Its sole conversation remains owned directly by its
  continuity.
- Storyline and Timeline conversation targets each require exactly one Entry.
- A Scene must resolve to a Storyline Entry; a Timeline Day must resolve to a
  Timeline Entry. Cross-mode subtype loading fails closed.
- Entry ownership is immutable. A conversation cannot move between Entries or
  continuities.
- Scene order and Timeline day order continue to be append-only and consecutive
  within their independent continuities.
- Timeline temporal eligibility still uses immutable position rather than local
  date or UTC ordering.
- Branch compatibility still depends on the exact selected persona checkpoint;
  sharing an Entry does not make off-branch evidence eligible.
- Memory occurrence cannot be later than learning. Learned Entry is the exact
  source Entry for extracted evidence.
- Corrections, exclusion, reactivation, and hard deletion preserve their current
  memory lifecycle semantics.
- Evolution corrections retain exact source provenance and replay semantics.
- Scene setup, Timeline boundary facts, summaries, and transcripts do not become
  generic Entry data merely to reduce type count.
- Shared code must not switch on ad hoc attribute presence such as `hasattr` or
  pair optional Scene and Day identifiers.
- Genuine mode differences may use a discriminated type, protocol adapter, or
  mode-specific service. The goal is shared meaning, not removal of legitimate
  polymorphism.
- Chat and Characters remain isolated, and neither product area imports the
  other.

## Persistence target

Add `characters.continuity_entries` as the normalized parent table for Scene and
Timeline Day records. At minimum it owns:

- `id`
- `continuity_id`
- `identity_id`
- `persona_id`
- `conversation_id`
- `mode`
- `position`

Use complete composite uniqueness and foreign keys so every Entry matches its
continuity and conversation ownership. Enforce:

- Mode is `storyline` or `timeline`.
- Position is positive.
- `(continuity_id, position)` is unique.
- One conversation belongs to at most one Entry.
- The continuity and conversation modes equal the Entry mode.

Refactor `characters.scenes` and `characters.timeline_days` into one-to-one subtype
tables keyed by the Entry identifier. Common ownership, conversation, mode, and
position facts have one source of truth in `continuity_entries`; do not leave
unconstrained duplicate columns in subtype tables.

Rename `characters.storyline_memories` to `characters.continuity_memories` and
replace the parallel nullable Scene/Day provenance columns in memory evidence and
extraction effects with required Entry foreign keys. Memory evidence uses:

- `entry_id`
- `occurrence_entry_id`
- `learned_entry_id`

Entry-backed evolution effects add an explicit Entry foreign key suitable for
database ownership validation. Ongoing effects remain entryless under a check
constraint tied to their evidence kind or owning mode. Serialized strategy audit
data may retain a validated Entry reference, but relational ownership must not
depend only on JSON inspection.

Development data is disposable, but the migration must still be deterministic and
reviewable. Preserve identities, personas, continuities, conversations, messages,
Scenes, and Timeline Days while normalizing their structure. Affected derived
memory and evolution records should be transformed when the mapping is exact. If
any derived record cannot be transformed without guessing, fail the migration or
explicitly rebuild only that affected derived boundary; never silently attach it
to a different Entry.

## Delivery and verification rules

This plan is a prerequisite for Stage 8 Slice 10. Do not begin Timeline evolution
feature work until every slice here is complete.

Implement slices in order. Each slice must leave Chat and Characters runnable and
must keep the existing Ongoing, Storyline, and delivered Timeline behavior passing.
Temporary compatibility adapters are allowed only when a slice explicitly calls
for them. The final slice removes all aliases, dual fields, deprecated exports,
and fallback paths.

Domain values and protocols belong in `characters/domain/`; shared orchestration
and eligibility belong in `characters/application/`; SQLAlchemy models and
repositories belong in `characters/infrastructure/`; prompt rendering remains in
`characters/prompts/`; mode-specific UI remains in `characters/ui/`.

Persistence changes use forward-only revisions after the current Characters head.
Never edit an applied migration. Verify fresh upgrade, upgrade from the current
Stage 8 head, downgrade to the preceding head where the destructive implications
are understood, and re-upgrade on disposable PostgreSQL. Render offline SQL and
reject all references to the `chat` schema. Compare representative Chat schema
objects, rows, and `chat.alembic_version` before and after the migration chain.

Every implementation slice adds or updates focused tests. Use fake providers and
injected clocks. Add PostgreSQL coverage for composite ownership, subtype mode,
position uniqueness, concurrent writes, and migration behavior. Do not require
Ollama, network access, wall-clock timing, or the process timezone in CI.

Run the smallest relevant checks for each slice. The final slice runs the
CI-equivalent commands independently:

```bash
timeout 30s uv run black --check src tests
uv run isort --check-only src tests
uv run ruff check src tests
uv run mypy src tests
uv run pytest -v
```

If Black times out, do not retry it during that run. Continue the remaining checks
and report the timeout. Fix a normal formatting failure and rerun Black once with
the same cap.

## Slice sequence

| Slice | Self-contained outcome | Depends on | Database impact |
|---|---|---:|---|
| 1 | Record the Entry decision and complete the structural inventory | Stage 8 Slice 9 | None |
| 2 | Add executable Entry domain and repository contracts | 1 | None |
| 3 | Normalize Scene and Timeline Day persistence around Entries | 2 | Characters migration |
| 4 | Unify Continuity memory domain and persistence | 2–3 | Characters migration |
| 5 | Consolidate memory selection, extraction, management, and composition | 4 | Existing Entry and memory records |
| 6 | Normalize evolution provenance, snapshots, and replay around Entries | 3–5 | Characters migration or JSON transformation |
| 7 | Remove transitional concepts and prove architectural isolation | 1–6 | Verification only |
| 8 | Reconcile durable design and Stage 8 delivery plans | 1–7 | None |

## Slice details

### Slice 1 — Record the Continuity Entry decision and inventory

Status: Complete

Add a concise ADR defining Continuity Entry, its ownership, its relationship to
Scene and Timeline Day, its position semantics, and the boundary between shared
structure and subtype behavior. Reconcile it with ADRs 006, 008, 009, 011, 025,
031, 032, 034–039.

The decision must settle:

- Why Entry is shared architecture vocabulary while Scene and Day remain product
  vocabulary.
- Which fields belong to the Entry parent and which remain subtype details.
- Whether `Scene` and `TimelineDay` inherit from or contain an immutable
  `ContinuityEntry`; choose one representation and use it consistently.
- How Ongoing remains entryless.
- How Storyline and Timeline targets carry Entry ownership.
- How selected graph checkpoints interact with Entry temporal position.
- How Entry-backed memory and evolution evidence differs from Ongoing evidence.
- How database subtype integrity is enforced without polymorphic foreign keys.

Complete a repository-wide inventory of structurally shared Scene/Day concepts,
including:

- Conversation targets and mode adapters.
- Scene and Timeline navigation snapshots.
- Branch-mode facts and graph-action inputs.
- Memory values, commands, selectors, prompts, repositories, management, UI, and
  fork provenance.
- Evolution evidence, effects, snapshots, selectors, replay, correction,
  observability, persistence, and prompts.
- Summary and conversation ownership constraints.
- Migration and architecture tests containing Storyline-first names.

Classify each item as shared Entry structure, genuine Scene behavior, genuine Day
behavior, Ongoing-only behavior, or user-facing terminology. Do not rename a
genuinely differentiated concept merely for symmetry.

Complete when the terminology and ownership model are precise enough that later
slices do not need to guess whether a field belongs to Entry, Scene, Day, or
Ongoing.

Delivered by [ADR 040](../../docs/decisions/040-use-continuity-entries.md) and the
[Continuity Entry structural inventory](CONTINUITY_ENTRY_INVENTORY.md).

### Slice 2 — Add executable Entry domain and repository contracts

Status: Complete

Add immutable Pydantic values for `ContinuityEntry` and `EntryPosition`. Export
them at the Characters domain boundary with complete field descriptions and
cross-field validation.

Refactor shared domain contracts so:

- `ConversationTarget` uses one `entry_id` for Storyline and Timeline, while
  Ongoing requires no Entry.
- Scene and Timeline Day snapshots expose their exact Entry without duplicating
  shared ownership or position semantics.
- Navigation values verify subtype mode, continuity ownership, unique IDs, and
  consecutive positions through Entries.
- Shared branch and temporal inputs use Entry references only when the rule truly
  applies to both modes.
- `ScenePosition`, `DayPosition`, and `MemoryPosition` stop being accepted by new
  code. They may remain as narrowly scoped transitional adapters until Slice 7,
  but may not be exported as the preferred API.

Define a read-only `ContinuityEntryRepository` protocol for exact owned lookup and
ordered continuity listing. Keep Scene and Timeline Day repositories for
subtype-specific reads and writes. Do not combine calendar closure and Scene setup
operations into the Entry repository.

Add domain tests for:

- Mode and subtype mismatches.
- Foreign continuity, identity, persona, and conversation ownership.
- Duplicate and non-consecutive positions.
- Ongoing targets that incorrectly name an Entry.
- Storyline and Timeline targets missing an Entry.
- Frozen values and invalid position comparisons.

Complete when application code can express shared structural ownership without a
Scene/Day union or paired nullable identifiers.

Delivered by the exported `ContinuityEntry`, `EntryPosition`, and read-only
`ContinuityEntryRepository` contracts. Scene and Timeline Day snapshots now contain
their exact Entry, and conversation targets use one `entry_id` for both narrative
modes while Ongoing remains entryless.

### Slice 3 — Normalize Scene and Timeline Day persistence around Entries

Status: Complete

Add `ContinuityEntryModel`, `DbContinuityEntryRepository`, and one reviewed
Characters migration. Normalize existing Scene and Timeline Day persistence into
one Entry parent with one-to-one subtype detail rows.

Update Storyline and Timeline repositories transactionally:

- Starting a Storyline creates its initial Entry, Scene details, and conversation
  atomically.
- Appending a Scene locks the Storyline, allocates the next Entry position, and
  creates Scene details and conversation atomically.
- Reserving a Timeline's first interaction creates its Entry, Day details,
  conversation, first input, and attempt atomically.
- Merely opening a Timeline still creates no Entry or Day.
- Closure updates only Timeline Day details and never mutates Entry identity,
  mode, ownership, conversation, or position.
- Scene setup locking updates only Scene details.

Update foreign keys and repository queries so consumers resolve shared ownership
through `continuity_entries`. Do not issue direct SQLAlchemy queries from services
or UI code.

Migration tests must cover:

- Fresh upgrade and current-head upgrade with representative Scenes and Timeline
  Days.
- Exact preservation of core IDs, ownership, conversations, order, calendar
  facts, setup state, graph selection, messages, attempts, and summaries.
- Rejection of a Scene detail attached to a Timeline Entry and a Day detail
  attached to a Storyline Entry.
- Duplicate position and conversation ownership.
- Concurrent Scene append and Timeline first-send allocation.
- Downgrade and re-upgrade on disposable PostgreSQL.
- Unchanged Chat schema objects, rows, and version table.

Complete when Entry is the sole persistence source of shared structural facts and
both mode-specific repositories retain their current observable behavior.

Delivered by `ContinuityEntryModel`, `DbContinuityEntryRepository`, and Characters
revision `f3a7c9e1b2d4`. Scene and Timeline Day tables now contain only their
subtype details plus a constrained fixed-mode Entry reference; shared ownership,
conversation, mode, and position resolve through `continuity_entries`. Storyline
start and append, Timeline first-send reservation, closure, setup locking,
summaries, memory validation, evolution validation, and structural forks all use
the normalized Entry boundary without changing their observable mode behavior.
Existing transitional memory provenance foreign keys now target Entries while
retaining the Slice 4 domain shape.

### Slice 4 — Unify Continuity memory domain and persistence

Status: Pending

Replace the Storyline-first memory model with one real Continuity memory model.
This is a rename and normalization, not an alias layer.

Domain work includes:

- Replace `StorylineMemory` with `ContinuityMemory`.
- Replace Scene/Day temporal values with `EntryPosition`.
- Replace `MemoryEvidence.scene_id/day_id` with required `entry_id` or one required
  `EntryPosition`, according to the Slice 1 decision.
- Require occurrence and learned `EntryPosition` values in the same continuity.
- Require learned Entry to be the source Entry and occurrence position not to
  exceed learned position.
- Replace `ExtractionEffect.scene_id/day_id` with one required Entry reference.
- Make memory commands, deltas, conflicts, revisions, response selections, and
  extraction snapshots use `ContinuityMemory` directly.
- Remove `ContinuityMemory = StorylineMemory` and `TimelineMemory =
  StorylineMemory` aliases.

Persistence work includes:

- Rename `storyline_memories` to `continuity_memories`.
- Rename `StorylineMemoryModel` to `ContinuityMemoryModel`.
- Replace source, occurrence, and learned Scene/Day columns with Entry foreign
  keys.
- Replace extraction-effect Scene/Day columns with one Entry foreign key.
- Preserve one continuity-owned lineage, current-revision uniqueness, subject
  uniqueness, evidence uniqueness, conflict lifecycle, and deletion cascades.
- Enforce exact Entry, conversation, continuity, profile, and mode ownership in
  the database.

Provide only `ContinuityMemoryRepository` and
`DbContinuityMemoryRepository`. Management commands remain continuity-scoped and
mode-isolated through ownership; they do not need separate Storyline and Timeline
repository types.

Test Storyline and Timeline create, reinforce, supersede, conflict, correct,
exclude, reactivate, delete, branch switch, as-of visibility, restart, and
cross-mode isolation using the same contracts. Include migration tests for
representative existing Storyline and Timeline memory rows.

Complete when memory has one domain vocabulary and one relational shape with no
paired nullable subtype fields or compatibility aliases.

### Slice 5 — Consolidate memory application workflows

Status: Pending

Refactor shared application behavior around Entry while retaining small
mode-specific context adapters for genuine differences.

Provide common services and strategies for:

- Entry- and branch-aware memory eligibility.
- Deterministic whole-record extraction budgeting.
- Delta extraction validation and idempotent effect application.
- Response-memory selection and independent budgeting.
- Memory inspection, correction, exclusion, reactivation, conflict dismissal,
  and hard deletion.
- Shared composition and provider capability wiring.

Use names such as `ContinuityMemoryEligibility`,
`ContinuityMemoryExtractionService`, `ContinuityResponseMemoryService`, and
`ContinuityMemoryService` where behavior is genuinely shared. Replace baseline
strategy identities that say `storyline` or `timeline` with one versioned
Continuity-memory identity when their behavior is identical.

Keep distinct adapters for inputs that are not shared:

- Storyline supplies Scene setup and selected Scene history.
- Timeline supplies current-day selected history and no prior-day transcript.
- Timeline closure policy runs before extraction reservation and commit.
- Ongoing supplies neither extracted long-term memory nor an Entry.

Do not represent these differences through `hasattr`, loosely typed dictionaries,
or paired optional fields. Prefer a small protocol or discriminated mode input
whose variants contain only their valid fields.

Update prompts to render `entry_id` and Entry positions without Scene/Day
introspection. Keep fixed source-evidence rules, record ordering, budgets,
provenance, and provider schemas deterministic.

Update composition so one memory extraction processor and one response-memory
provider can dispatch through the validated Entry mode rather than parallel
Storyline and Timeline service fields. Preserve the rule that response-context
insertion itself remains assigned to Stage 8 Slice 11.

Complete when Storyline and Timeline share the full memory lifecycle without
parallel service families, while their transcript and mode policies remain
explicit and testable.

### Slice 6 — Normalize evolution around Entry provenance

Status: Pending

Refactor existing Ongoing and Storyline evolution structure before enabling
Timeline evolution.

Domain work includes:

- Replace `EvolutionEvidenceKind.STORYLINE_CHECKPOINT` with an Entry-backed
  checkpoint concept.
- Represent Ongoing evidence and Entry-backed evidence with explicit validated
  shapes. Ongoing has no Entry; Entry-backed evidence requires an `EntryPosition`.
- Replace `scene_id` and `scene_position` in mode-neutral evolution contracts with
  Entry terminology.
- Preserve exact conversation, adjacent user/persona messages, source checkpoint,
  strategy versions, and projection revisions.
- Update deterministic evidence ordering to use Entry position followed by
  persona checkpoint for Entry-backed evidence.

Application work includes:

- Make snapshot selection, validation, effect reservation, replay eligibility,
  projection rebuild, correction, inspection, and observability understand
  Entry-backed evidence.
- Extract common Entry history traversal behind an adapter or protocol.
- Keep the delivered Storyline selector behavior, thresholds, prompts, event
  ordering, corrections, and replay results unchanged.
- Keep Timeline rejected with a stable unsupported-mode result. Do not add
  Timeline inference, Timeline projections, or Timeline correction UI in this
  refactor.

Persistence work includes:

- Add an optional relational Entry foreign key only where Ongoing versus
  Entry-backed evidence genuinely requires it.
- Constrain Ongoing effects to no Entry and Entry-backed effects to one exact
  owned Entry.
- Transform serialized Storyline source references to Entry terminology without
  losing exact message or strategy provenance.
- Preserve accepted events, corrections, rebuildable projections, and effect
  idempotency.

Test Ongoing evidence, Storyline Entry evidence, selected and deselected branches,
future Entry rejection, replay after selection, corrections, restart, migration,
and explicit Timeline rejection. Extend native evaluation fixtures only to prove
that the structural rename does not change Storyline decisions.

Complete when evolution no longer encodes a shared checkpoint as a Scene, yet
Timeline evolution remains a clean, unimplemented extension for Slice 10.

### Slice 7 — Remove transitional concepts and prove isolation

Status: Pending

Delete every temporary adapter, alias, deprecated export, paired identifier, and
fallback path introduced to keep earlier slices runnable.

At minimum remove or reject:

- `ScenePosition`
- `DayPosition`
- `MemoryPosition`
- `StorylineMemory`
- `TimelineMemory`
- `StorylineMemoryRepository`
- `TimelineMemoryRepository`
- `DbStorylineMemoryRepository`
- `DbTimelineMemoryRepository`
- `StorylineMemoryService`
- `TimelineMemoryService`
- `storyline_memories`
- Shared contracts containing both `scene_id` and `day_id`
- Shared prompt logic inspecting Scene/Day attribute presence
- Evolution contracts using Scene terminology for Entry-backed evidence

Do not remove legitimate Scene and Day names from mode-specific domain models,
repositories, policies, migrations predating this refactor, UI state, or
user-facing labels.

Add architecture tests that fail when obsolete shared names or dual-field shapes
return. Check package-boundary exports and ensure external modules import Entry,
memory, and evolution architecture symbols from their owning package boundaries.

Run complete migration and runtime proof:

- Fresh Characters upgrade.
- Upgrade from the current Stage 8 head.
- Downgrade and re-upgrade on disposable PostgreSQL.
- Offline SQL with no `chat` schema references.
- Representative Chat row, object, and version-table comparison.
- Ongoing, Storyline, and Timeline lifecycle and conversation regression suites.
- Storyline and Timeline memory acceptance journeys.
- Ongoing and Storyline evolution acceptance and replay journeys.
- Area-boundary and lazy-initialization architecture tests.
- Full CI-equivalent checks.

Complete when the repository has one coherent Entry vocabulary, no transitional
memory names, structurally prepared evolution, and unchanged delivered behavior.

### Slice 8 — Reconcile durable design and Stage 8 delivery plans

Status: Pending

Update `DESIGN.md` because Entry changes the durable domain model, persistence
ownership, and extension seams. Reconcile all accepted ADRs and describe the
resulting design directly rather than recording the refactor history. Update the
design document's `Last updated` date.

Update the Stage 8 master plan and ongoing TODO so Slice 10 is the next focus only
after this plan is complete. Revise Slice 10 terminology to use Entry-backed
evolution while preserving its Timeline behavior and acceptance criteria.

Do not update `README.md` unless the refactor changes shipped user-visible
behavior, setup, configuration, privacy, or operator workflow. Entry is normally
an internal architectural concept and should not replace Scene or Day in product
documentation.

Run:

```bash
git diff --check -- DESIGN.md work/ongoing/PLAN.md \
  work/ongoing/CONTINUITY_ENTRY_REFACTOR_PLAN.md work/ongoing/TODO.md
```

Complete when durable design documentation, delivery status, and the next Slice
10 implementation all use the final Entry architecture consistently.

## Refactor completion criteria

The complete refactor is accepted only when all of the following are true:

- Scene and Timeline Day resolve through one normalized Continuity Entry parent.
- Shared ownership and position facts have one domain and persistence source of
  truth.
- Memory uses one Continuity vocabulary from domain through UI and database.
- Memory evidence and extraction effects have one required Entry owner.
- Entry-backed evolution provenance and replay use Entry terminology and foreign
  keys.
- Ongoing remains entryless and memory-free.
- Timeline evolution remains disabled pending Stage 8 Slice 10.
- No compatibility alias or dual Scene/Day field remains in shared architecture.
- Existing mode-specific behavior and user-facing terminology are preserved.
- Characters migrations do not touch Chat.
- The full suite and migration isolation checks pass.
