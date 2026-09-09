# Chat Buddy Execution Plan

Status: Initial plan, living document  
Last updated: 2026-09-09

## How to use this plan

This document tracks the current implementation sequence. Update it whenever
scope, ordering, or acceptance criteria change. During implementation, load the
current stage and only the directly relevant sections of `DESIGN.md`; do not load
both documents wholesale unless a cross-cutting decision requires it.

Each stage should be delivered as one or more cohesive changes with focused unit
tests, integration coverage when service and repository boundaries are crossed,
and the repository quality checks passing.

## Target architecture

The main domain aggregates are:

- `Identity`: editable until first use, then frozen.
- `Persona`: immutable authored definition.
- `Continuity`: identity/persona relationship boundary and mode owner.
- `Conversation`: Chat thread, Storyline scene, or Timeline day.
- `Message`: immutable node in a selectable branch.
- `Memory`: continuity-scoped knowledge with temporal and source provenance.
- `RelationshipEvent`: append-only evidence, correction, or milestone.
- `RelationshipState`: current relationship projection.

Application services depend on repository `Protocol` interfaces declared in the
domain layer. Infrastructure repositories implement those interfaces, and
`ui/streamlit_app.py` remains the composition root.

## Stage 0 — Record the behavioral contract

Create focused decision records for:

- Terminology and continuity ownership.
- Identity freezing and persona immutability.
- Mode-specific context and memory rules.
- Branch and retry behavior.
- Relationship intent, evolution, and explicit milestones.
- Timeline timezone and closure semantics.
- Migration of existing conversations and global memories.

Add behavior scenarios covering isolation, temporal memory, established starting
relationships, branching, and closed Timeline days.

**Complete when:** ambiguous rules are resolved before schema work and the
decisions agree with `DESIGN.md`.

## Stage 1 — Build domain and persistence foundations

- Add immutable domain models and enums for identities, personas, continuities,
  modes, lifecycle states, and relationship starting state.
- Add repository protocols to the domain layer.
- Refactor application services so they do not import concrete infrastructure
  repositories.
- Add SQLAlchemy models and repositories for Identity, Persona, and Continuity.
- Extend Conversation to belong to a Continuity and support mode-specific
  metadata.
- Enforce one active Chat and one active Timeline per identity/persona pair;
  permit multiple named Storylines.
- Lock an identity transactionally when its first continuity starts.
- Generate and review an Alembic migration.

Migration policy:

- Preserve existing conversations under imported default identity/persona data.
- Preserve old conversations as archived legacy Chat continuities.
- Preserve global memories for review, but do not silently inject them into new
  continuities.
- Verify migration against populated PostgreSQL data before release.

**Complete when:** lifecycle invariants are tested, existing data survives, and
service dependencies point inward.

## Stage 2 — Deliver Chat on the new model

- Add the start flow: identity, persona, Chat mode, relationship intent, optional
  established state, then confirmation.
- Lock the identity when the continuity begins.
- Implement grouped Identity → Persona → Ongoing Chat navigation.
- Build a mode-aware context assembler with this ordering:

```text
Persona → Identity → Relationship → Memories → Scene/style → Conversation
```

- Keep Chat free of extracted long-term memory.
- Retain rolling conversation summaries as Chat-local context compression.
- Add recoverable generation state so a streaming failure does not leave an
  ambiguous half-turn.

**Complete when:** the new Chat has current feature parity, resumes correctly,
has no memory leakage, and works end to end through Streamlit.

## Stage 3 — Add retry and branching

- Make messages immutable nodes with parent-message relationships.
- Track the selected conversation leaf/path.
- Implement persona-response alternatives for retry.
- Enforce and display the retry limit in the service and UI.
- Implement **Branch from here** without deleting the old path.
- Include only the selected path in model context and downstream extraction.
- Record response style/generation metadata with persona messages.

Mode policy:

- Chat branches in place.
- The latest Storyline scene branches in place; changing an older scene forks the
  Storyline.
- An open Timeline day branches in place; a closed day requires a Timeline fork.

**Complete when:** old paths remain recoverable, retries cannot leak into current
state, and branch selection is covered by repository and application tests.

## Stage 4 — Add Storylines and scoped memory

- Add named Storylines with chronologically ordered scenes.
- Store scene setup separately from title and response style.
- Lock scene order after interaction begins.
- Replace global key/value memory with continuity-scoped, provenance-aware memory.
- Track source message, selected branch, occurrence time, learned time, and
  active/superseded/excluded/deleted state.
- Extract memory only after a complete turn, using both sides of the exchange.
- Add memory inspection, correction, exclusion, and hard deletion UI.
- Enforce as-of memory queries so a scene cannot see future knowledge.
- Fork the Storyline when branching an older scene with dependent scenes.

**Complete when:** Storylines are isolated, temporal memory rules hold, user
corrections immediately affect context, and later raw transcripts are unnecessary.

## Stage 5 — Add relationship evolution

- Persist append-only Relationship Events and a current Relationship State
  projection.
- Support social status, romantic status, current dynamic, qualitative supporting
  dimensions, boundaries, and milestones.
- Implement relationship-intent constraints.
- Have extraction produce structured proposals rather than direct state changes.
- Validate proposals in an application service against domain transition rules.
- Require explicit evidence for partnership, engagement, marriage, breakup, and
  reconciliation.
- Add conservative transition thresholds and hysteresis.
- Add provenance and user correction UI; avoid numeric progress indicators.
- Rebuild relationship state correctly when a branch or continuity is forked.

**Complete when:** platonic boundaries hold, major milestones cannot arise from
vague sentiment, and relationship state is explainable and branch-correct.

## Stage 6 — Add Timeline

- Add one dated conversation per active local day.
- Store UTC timestamps plus the resolved, immutable local date.
- Add a domain Clock abstraction and IANA timezone policy.
- Close days after their local boundary, including when the app was offline.
- Reject messages, retries, and in-place branches for closed days.
- Create no records for days without interaction.
- Use current-day messages as short-term context and eligible prior memory and
  relationship state as long-term context.
- Apply timezone changes only to future boundaries.
- Support forking a Timeline from a closed historical point.

**Complete when:** day closure, missing-day behavior, timezone changes, temporal
memory, and fork rules are deterministic and tested, including DST boundaries.

## Stage 7 — Add response-style controls and UX refinement

- Add scene-description level, response length, narrative placement, dialogue
  formatting, and tone controls.
- Apply style changes from the next persona response without affecting facts or
  relationship state.
- Record the effective style with every generated persona message.
- Complete sidebar navigation with mode badges, active/archived state, recent
  items, and search as needed.
- Add branch, memory, and relationship inspectors.
- Improve persona duplication, identity duplication, continuity archive, and
  continuity fork flows.

**Complete when:** presentation controls are predictable, navigation remains clear
with substantial data, and destructive implications are never hidden.

## Stage 8 — Harden and prepare for release

- Add PostgreSQL migration tests in addition to SQLite repository tests.
- Test every domain invariant directly.
- Add integration tests for service/repository workflows.
- Add Streamlit interaction tests for creation, grouping, locking, branching, and
  closed states.
- Add prompt/context snapshot tests for every mode.
- Test isolation among identities, personas, continuities, modes, and branches.
- Add observability for generation, extraction, relationship validation, and
  context assembly failures.
- Verify export and deletion of identities, memories, and complete continuities.
- Document required migration, PostgreSQL, and Ollama setup changes.

**Complete when:** the full quality suite passes and failure, migration, recovery,
privacy, and isolation behavior are release-ready.

## Initial delivery milestone

Implement Stages 0–2 first:

> A user can create a frozen identity, create an immutable persona, start one Chat
> continuity with relationship intent, converse through the scoped context
> pipeline, and resume it from the grouped sidebar.

Implement branching immediately afterward. Memory and relationship evolution
should not be built on a permanently linear message model.

## Validation baseline

Before completing each implementation stage, run:

```bash
black --check src tests
isort --check-only src tests
ruff check src tests
mypy src tests
pytest -v
```

Use `scripts/check.sh` when it represents the same current CI checks. Add focused
unit tests beside the affected layer and integration tests whenever a change
crosses service and repository boundaries.
