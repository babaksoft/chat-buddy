# Continuity Entry structural inventory

Status: Complete

Last updated: 2026-11-04

## Purpose

This inventory classifies the current Scene/Day structure before the Continuity
Entry refactor. [ADR 040](../../docs/decisions/040-use-continuity-entries.md)
settles the target ownership model. This document records implementation seams for
Slices 2–7; it does not rename user-facing Scene or Day concepts and does not
authorize changes to applied migrations.

The classifications used below are:

- **Entry** — shared immutable structure owned by `ContinuityEntry` or
  `EntryPosition`.
- **Scene** — genuine Storyline-only behavior.
- **Day** — genuine Timeline-only behavior.
- **Ongoing** — behavior that remains deliberately entryless.
- **Product** — user-facing Scene, Day, Storyline, or Timeline terminology.

## Structural ownership

| Current location | Current shape | Classification and target |
|---|---|---|
| `domain/continuity.py` | Continuity identity, persona, mode, lifecycle, and Ongoing `conversation_id` | **Ongoing** keeps its direct conversation. Storyline/Timeline Entry ownership is added separately; lifecycle and starting relationship stay continuity-owned. |
| `domain/conversation.py` | `ConversationTarget` pairs optional `scene_id` and `day_id` with a `ConversationScope` | **Entry**: one optional `entry_id`, forbidden for Ongoing and required for Storyline/Timeline. The scope still carries exact conversation and continuity ownership. |
| `domain/storyline.py` | `Scene` repeats `id`, `scope`, and `position` beside `SceneDetails` and `setup_locked` | Contain one **Entry**; keep details, setup locking, append policy, revisions, and fork/navigation rules as **Scene**. |
| `domain/timeline.py` | `TimelineDay` repeats `id`, `scope`, and `position` beside boundary and closure facts | Contain one **Entry**; keep date, timezone, UTC boundaries, closure, settled leaf, reservation, and calendar guards as **Day**. |
| `domain/storyline.py` / `domain/timeline.py` | `SceneSequence` and `TimelineNavigation` independently validate ownership, unique conversations, and consecutive positions | Validate common identity, continuity, conversation, mode, unique Entry IDs, and consecutive **Entry** positions through contained Entries. Retain Scene setup-lock and Day date/closure checks in their subtype snapshots. |
| `domain/repositories.py` | Separate Scene and Day repositories expose common lookup/listing plus subtype writes | Add a read-only **Entry** repository for owned lookup and ordered listing. Keep Scene setup/append and Day reservation/closure operations on subtype repositories. |

`ContinuityEntry` is therefore the single owner of `id`, `continuity_id`,
`identity_id`, `persona_id`, `conversation_id`, `mode`, and `position`.
`EntryPosition` carries `entry_id`, `continuity_id`, `mode`, and `position` for
portable temporal provenance. Scene and Day snapshots use composition, not
inheritance.

## Conversation targets, navigation, and graph actions

| Seam | Files and symbols | Classification and later-slice action |
|---|---|---|
| Target construction and dispatch | `domain/conversation.py`; `application/storyline_conversation.py`, `timeline_conversation.py`, `conversation_service.py`, `context_service.py`; `ui/ongoing.py`, `ui/storylines_page.py` | `ConversationTarget.entry_id` is **Entry** structure. Ongoing adapters require no Entry; Storyline and Timeline adapters resolve and validate their subtype. UI labels remain **Product** terminology. |
| Storyline navigation and append | `SceneSequence`, `SceneAppendEligibility`, `StorylineForkSource`, `StorylineForkPreview`; `application/storyline_service.py`, `storyline_fork_service.py`, `branch_policy.py` | Sequence identity/position is **Entry**. Setup locking, latest-Scene append, prior-Scene fork requirements, and fork provenance are genuine **Scene** behavior. Mode-neutral graph input should use Entry references only where both modes share the rule. |
| Timeline navigation and graph guards | `TimelineNavigation`, `TimelineGraphActionAvailability`; `application/timeline_service.py`, `timeline_day_service.py`, `branch_policy.py` | Sequence identity/position is **Entry**. Local-date ordering, latest-open-Day writability, closure, no-fork policy, and unavailable reasons remain **Day** behavior. |
| Graph persistence | `infrastructure/db/repositories/conversation_repository.py`, `scene_repository.py`, `timeline_day_repository.py`, `storyline_fork_repository.py` | Conversation ownership resolves through **Entry**. Selected-leaf checks and immutable ancestry remain conversation-graph behavior; Scene append/fork and Day closure locks remain subtype-specific. |

An Entry position never proves branch eligibility. `SelectedPath`, exact parent
ancestry, selected persona-message checkpoints, and expected-leaf guards remain
the branch authority in `domain/branching.py` and the conversation repositories.

## Memory and extraction

| Seam | Current locations | Classification and target |
|---|---|---|
| Temporal values and evidence | `domain/memory.py`: `ScenePosition`, `DayPosition`, `MemoryPosition`, `MemoryEvidence` | Replace with **Entry** `EntryPosition`. Source, occurrence, and learned evidence each names one Entry; learned equals source and occurrence is not later. |
| Memory vocabulary | `StorylineMemory`, `ContinuityMemory` alias, `TimelineMemory` alias; repository and service aliases at package boundaries | One real **Entry-backed** `ContinuityMemory`, `ContinuityMemoryRepository`, `DbContinuityMemoryRepository`, and `ContinuityMemoryService`; remove Storyline/Timeline aliases by Slice 7. |
| Extraction effects | `domain/memory.py` and `memory_extraction.py`; `MemoryExtractionRepository` | Replace paired `scene_id`/`day_id` with one source `entry_id`. Exact conversation and persona checkpoint remain required branch evidence. |
| Eligibility and selection | `application/memory_context.py`, `response_memory.py`, `evolution_snapshot.py` | Consolidate position and selected-ancestry checks around **Entry**. Storyline prior-Scene history is a **Scene** adapter; Timeline current-Day history, closure ordering, and exclusion of prior-Day transcripts are **Day** adapters. |
| Extraction and management | `application/memory_extraction_service.py`, `memory_service.py`, `context_service.py`; `infrastructure/llm/memory_extraction.py` | Delta validation, idempotent effects, lifecycle commands, and budgeting are shared Continuity behavior. Reservation timing before Timeline closure remains **Day** behavior. |
| Prompts and UI | `prompts/memory_extraction.py`, `prompts/storyline.py`; `ui/storyline_memory.py`, `ui/storylines_page.py` | Prompt schemas use Entry identity without attribute inspection. UI continues to present **Product** Scene/Day wording; the existing Storyline-only management surface may be generalized without exposing “Entry” to users. |
| Fork provenance | `domain/storyline.py`; `application/storyline_fork_service.py`; `infrastructure/db/repositories/storyline_fork_repository.py` | Remap source/occurrence/learned **Entry** IDs when copying eligible memory. The decision to copy and the reviewed Storyline fork remain **Scene** behavior. Timeline has no fork. |

The affected test seams are `tests/characters/domain/test_storyline_memory.py`,
`test_memory_extraction_contracts.py`, `test_memory_protocols.py`, application
memory/context tests, UI memory tests, and the Storyline/Timeline memory repository,
PostgreSQL, fork, and acceptance suites under `tests/integration/characters/`.

## Evolution

| Seam | Current locations | Classification and target |
|---|---|---|
| Evidence shape and ordering | `domain/evolution.py`: `EvolutionEvidenceKind`, `EvolutionEvidenceReference`, `_evidence_position` | Split explicit **Ongoing** turn evidence from **Entry-backed** checkpoint evidence. Replace Storyline `scene_id`/`scene_position`; order Entry evidence by Entry position then persona checkpoint. |
| Effect reservation and validation | `application/evolution_effect_service.py`; `infrastructure/db/repositories/evolution_repository.py` | Ongoing effects require no Entry. Entry-backed effects require an exact owned Entry plus conversation and source persona message. Timeline remains explicitly unsupported until Stage 8 Slice 10. |
| Snapshot selection | `application/evolution_snapshot.py`, `baseline_evolution_strategy.py` | Shared selected-history, budget, memory, and strategy logic uses Entry provenance. Ongoing traversal stays entryless; current Storyline traversal becomes an Entry history adapter; Timeline traversal is not enabled by this refactor. |
| Replay, correction, and inspection | `application/evolution_projection_service.py`, `evolution_inspection_service.py`, `evolution_observability.py`; `ui/evolution_inspection.py`; `prompts/evolution.py` | Replay and corrections retain exact source provenance and selected-branch checks. Observability and prompts use neutral Entry wording for Entry-backed evidence; user surfaces may still name the concrete Scene or Day. |
| Persistence | `infrastructure/db/models/evolution.py`, `repositories/evolution_repository.py` | Add relational Entry ownership for Entry-backed effects. Serialized audit provenance may mirror Entry data but is not its ownership constraint. Ongoing rows are constrained entryless. |

Focused coverage currently lives in `tests/characters/domain/test_evolution.py`,
the evolution application tests, and integration suites for effect processing,
snapshots, projection replay, corrections, persistence, and observability. These
tests must distinguish Ongoing from Entry-backed shapes and continue rejecting
Timeline execution until Slice 10.

## Summaries and conversation ownership

Messages, generation attempts, graph nodes, and summary revisions remain owned by
their exact `ConversationScope`. Entry does not absorb transcript or summary
content.

- `infrastructure/db/models/message.py` and `repositories/conversation_repository.py`
  must constrain Storyline/Timeline conversations through the owning Entry while
  preserving Ongoing's direct continuity ownership.
- `domain/summary.py`, `application/rolling_summary_service.py`, and
  `infrastructure/db/models/summary.py` remain conversation-scoped.
- `infrastructure/db/repositories/summary_repository.py` currently joins Scene or
  Day to enforce write policy. It should resolve common ownership through Entry,
  then retain latest-Scene and latest-open-Day guards in subtype-specific policy.
- Summary checkpoint compatibility remains selected-ancestry behavior, not Entry
  position behavior.

## Persistence and migration inventory

| Current object | Target classification |
|---|---|
| `ContinuityModel`, `ConversationModel` in `infrastructure/db/models/continuity.py` | Continuity ownership remains shared; add the **Entry** parent and exact conversation/continuity/mode constraints. Ongoing conversation stays directly continuity-owned. |
| `SceneModel` | One-to-one **Scene** detail keyed by a Storyline Entry. Move identity, persona, continuity, conversation, mode, and position to Entry; retain title, setup, and setup lock. The optimistic revision remains on the Storyline. |
| `TimelineDayModel` | One-to-one **Day** detail keyed by a Timeline Entry. Move shared ownership and position to Entry; retain calendar boundaries, closure, and settled leaf. |
| `StorylineMemoryModel`, `MemoryEvidenceModel`, `MemoryExtractionEffectModel` | Rename to Continuity memory and replace all paired Scene/Day provenance columns with required **Entry** foreign keys. |
| `EvolutionEffectModel` | Add a nullable Entry foreign key constrained by explicit Ongoing versus Entry-backed evidence kind. |

Applied revisions
`e42b7c91d5a0_persist_storylines_and_scenes.py`,
`b17c4e92a6d1_persist_storyline_memory.py`,
`9c4e7a1b2d30_persist_timelines_and_response_style.py`, and
`d6e8f1a2b3c4_add_timeline_memory.py` contain the legacy names and shapes. They
remain unchanged. New forward revisions must transform them deterministically and
must not touch the `chat` schema.

PostgreSQL suites that enumerate old tables or assert direct Scene/Day ownership
include `test_storyline_postgres.py`, `test_timeline_postgres.py`,
`test_storyline_memory_postgres.py`, `test_stage_four_postgres.py`,
`test_stage_six_postgres.py`, and `test_identity_postgres.py`. The Stage 8 Entry
migration tests must cover fresh/current-head upgrade, downgrade/re-upgrade,
offline SQL isolation, representative data preservation, subtype-mode rejection,
position and conversation uniqueness, concurrent allocation, and unchanged Chat
objects, rows, and version state.

## Package and architecture seams

- Update `domain/__init__.py`, `application/__init__.py`, model/repository package
  exports, and `tests/architecture/test_package_exports.py` as contracts move.
- Extend `tests/architecture/test_area_boundaries.py` and Characters layer tests to
  keep Chat and Characters isolated and persistence behind repositories.
- Extend `tests/architecture/test_migration_isolation.py` for the new Characters
  revisions and absence of `chat` schema references.
- Add an obsolete-vocabulary architecture check in Slice 7. It should reject
  shared `ScenePosition`, `DayPosition`, `MemoryPosition`, Storyline/Timeline
  memory aliases, paired Scene/Day identifiers, and Scene-named Entry evolution
  contracts while allowing legitimate subtype, UI, and historical migration
  terminology.

## Slice routing

| Slice | Inventory boundary |
|---|---|
| 2 | Entry values, composed snapshots, target/navigation validation, read-only Entry repository protocol. |
| 3 | Entry parent persistence, subtype tables, repositories, summaries/conversation ownership, and normalization migration. |
| 4 | Continuity memory domain, Entry provenance, persistence rename, and migration. |
| 5 | Shared memory eligibility, extraction, management, response selection, prompts, and composition with mode adapters. |
| 6 | Entry-backed evolution evidence, persistence, snapshot/replay/correction behavior, with Timeline execution still rejected. |
| 7 | Remove aliases and paired fields; enforce package, vocabulary, migration, and area isolation. |

No inventoried concept requires replacing Scene or Day in product language. No
genuine calendar, closure, setup, append, or fork behavior is generalized merely
for naming symmetry.
