# Chat Buddy Execution Plan

Status: Living plan

Last updated: 2026-09-16

## How to use this plan

This document tracks the implementation sequence for two independent product
areas hosted temporarily in one application. Update it whenever scope, ordering,
or acceptance criteria change. During implementation, load the current stage and
only the directly relevant sections of `DESIGN.md`.

Each stage should be delivered as one or more cohesive changes with focused unit
tests, integration coverage when service and repository boundaries are crossed,
and the repository quality checks passing.

## Target architecture

The Streamlit shell routes between two area-first modules:

```text
src/chat_buddy/
├── chat/
│   ├── domain/
│   ├── application/
│   ├── infrastructure/
│   ├── prompts/
│   └── ui/
├── characters/
│   ├── domain/
│   ├── application/
│   ├── infrastructure/
│   ├── prompts/
│   └── ui/
├── shared/
└── ui/streamlit_app.py
```

Each area declares its own domain models and `Protocol` interfaces. Application
services depend inward on those protocols; infrastructure supplies database and
LLM adapters. The shared package is limited to generic configuration, logging,
and low-level provider utilities. Area-specific prompts, services, repositories,
and persistence are never shared.

PostgreSQL hosts independent `chat` and `characters` schemas. Each has its own
SQLAlchemy metadata, migration history, and Alembic version table. The areas have
no cross-schema foreign keys or queries and do not require compatible models or
migrations.

## Stage 0 — Record the behavioral contract

**Status: Complete.**

The initial identity, persona, continuity, context, branching, relationship, and
Timeline decisions are recorded in ADRs 006–011. ADR 013 narrows those decisions
to Characters and establishes the product-area boundary. ADR 014 replaces the
Ollama-only provider decision. ADR 012 is superseded because the new schema
baseline does not migrate legacy data.

## Stage 1 — Scaffold the bounded areas

**Status: Complete.**

- Create area-first Chat and Characters package trees with domain, application,
  infrastructure, prompts, and UI boundaries.
- Keep `ui/streamlit_app.py` as the thin composition root and initialize only the
  selected area's services.
- Move current conversation, context, summary, memory, Ollama, tokenization, and
  Chat UI code behind Chat-owned interfaces without changing visible behavior.
- Keep Characters as an independently routed scaffold that imports no Chat code.
- Introduce independent SQLAlchemy bases, metadata, session/repository wiring,
  and migration environments for the `chat` and `characters` schemas.
- Store migration versions in `chat.alembic_version` and
  `characters.alembic_version`.
- Retain the existing migration files unchanged as legacy history. Establish new
  clean baselines and document database recreation; do not map or preserve rows
  from the pre-split schema.
- Add architecture checks that reject imports between the two areas except for
  composition by the application shell.

**Complete when:** both areas load independently, current Chat behavior works from
its new module, fresh migrations create isolated schemas, and no area-specific
model, service, prompt, or repository remains in shared code.

## Stage 2 — Complete the Chat foundation

- Accept the focused Chat provider-capability and generation-lifecycle ADRs before
  implementation.
- Define Chat-owned provider, model, conversation, message, and generation-attempt
  domain contracts.
- Separate response generation from title generation, summarization, and memory
  extraction through capability-specific Chat-owned interfaces.
- Add a provider registry and persist the provider, model, and effective
  generation configuration used for each response. Keep the current selection on
  the conversation and an immutable effective snapshot on each generation
  attempt.
- Retain Ollama as the first local adapter and preserve streaming behavior.
- Keep provider-specific authentication and clients in infrastructure. Select and
  record each cloud vendor in a focused ADR before adding its adapter.
- Track pending, streaming, completed, failed, and interrupted generation
  attempts. Keep partial output outside completed history and allow an incomplete
  attempt to be retried without duplicating its user message.
- Keep the Chat UI focused on conversation selection, provider/model selection,
  history, and message generation.

**Complete when:** conversations can be created, resumed, and streamed through a
provider-neutral contract; Ollama remains functional; every completed response
has immutable generation provenance; incomplete attempts are visibly recoverable;
and a second test provider can be registered without changing Chat application
services.

## Stage 3 — Deliver automatic Chat context and memory

- Define the final Chat-owned summary and memory domain contracts, including
  provenance and lifecycle state.
- Separate context eligibility, token budgeting, rolling summarization, and
  memory extraction into Chat-owned services.
- Keep rolling summaries scoped to their source conversation.
- Replace the current unqualified key/value store with Chat-wide memories that
  record source provenance and active, superseded, excluded, or deleted state.
- Extract memory only after a complete user/assistant turn.
- Add memory inspection, correction, exclusion, and hard-deletion workflows.
- Assemble context from active Chat memories, the conversation summary, and
  recent messages within the selected provider's token budget.
- Add the first cloud-provider adapter after its provider ADR is accepted.

**Complete when:** long conversations remain coherent, active memory can be reused
across Chat conversations, summaries never cross conversations, users control
stored memory, and both a local and a cloud adapter pass the same contract tests.

## Stage 4 — Build Characters foundations and Ongoing mode

- Add immutable Characters domain models and enums for Identity, Persona,
  Continuity, Ongoing mode, lifecycle state, and relationship starting state.
- Add Characters-owned repository and LLM gateway protocols and infrastructure
  implementations.
- Add SQLAlchemy models and repositories only to the `characters` schema.
- Enforce identity freezing, immutable persona cores, continuity isolation, and
  at most one active Ongoing continuity per identity/persona pair.
- Add the start flow: identity, persona, Ongoing mode, relationship intent,
  optional established state, and confirmation.
- Implement grouped Identity → Persona → Ongoing navigation.
- Keep Ongoing free of extracted long-term memory; use only its rolling summary
  for context compression.
- Define a versioned Characters strategy interface for future persona and
  relationship evolution experiments.

**Complete when:** an identity and persona can start and resume an isolated
Ongoing continuity, lifecycle invariants hold transactionally, and no Chat record
or service participates in the workflow.

## Stage 5 — Add Characters retry and branching

- Make messages immutable nodes with parent-message relationships.
- Track the selected conversation leaf and include only that path in context and
  downstream derivation.
- Implement persona-response alternatives with a visible limit of three retries
  per persona turn.
- Implement **Branch from here** without deleting the existing path.
- Record response style, provider, model, strategy version, and generation
  metadata with persona messages.
- Apply mode rules: Ongoing branches in place; an older Storyline scene forks its
  Storyline; a closed Timeline day requires a Timeline fork.

**Complete when:** prior paths remain recoverable, unselected alternatives cannot
affect current state, and branch selection is covered by repository and
application tests.

## Stage 6 — Add Storylines and continuity-scoped memory

- Add named Storylines with chronologically ordered scenes.
- Store scene setup separately from title and response style and lock scene order
  after interaction begins.
- Add provenance-aware Characters memory scoped to a continuity and selected
  branch.
- Track source message, occurrence time, learned time, and active, superseded,
  excluded, or deleted state.
- Extract memory only after a complete turn and enforce as-of queries so a scene
  cannot see future knowledge.
- Add inspection, correction, exclusion, and hard-deletion UI.
- Fork the Storyline when branching an older scene with dependent scenes.

**Complete when:** Storylines and their memories are isolated, temporal rules
hold, corrections immediately affect context, and no Characters memory is
visible to Chat.

## Stage 7 — Add relationship and persona evolution

- Persist append-only relationship events and a current relationship-state
  projection.
- Support social status, romantic status, current dynamic, qualitative supporting
  dimensions, boundaries, and provenance-backed milestones.
- Have versioned evolution strategies produce structured proposals rather than
  direct state changes.
- Validate every proposal against relationship intent and domain transition
  rules before persistence.
- Require explicit evidence for partnership, engagement, marriage, breakup, and
  reconciliation; use conservative thresholds and hysteresis for gradual change.
- Add provenance and correction UI and rebuild derived state correctly after a
  branch or continuity fork.
- Compare experimental strategies only within Characters and promote a strategy
  only after its behavioral scenarios pass.

**Complete when:** relationship state is explainable and branch-correct,
boundaries and milestones hold, strategy versions are traceable, and evolution
has no Chat dependency or effect.

## Stage 8 — Add Timeline and response-style controls

- Add one dated conversation per active local Timeline day.
- Store UTC timestamps plus the resolved immutable local date and IANA timezone.
- Close days after their local boundary, including after offline periods, and
  reject messages, retries, and in-place branches for closed days.
- Create no records for days without interaction and apply timezone changes only
  to future boundaries.
- Use current-day messages as short-term context and eligible prior memory and
  relationship state as long-term context.
- Add scene-description level, response length, narrative placement, dialogue
  formatting, and tone controls.
- Apply style changes from the next persona response and record the effective
  style with every generated message.

**Complete when:** closure, missing-day behavior, timezone changes, temporal
memory, fork rules, and response styles are deterministic and tested, including
DST boundaries.

## Stage 9 — Harden and prepare Characters extraction

- Add PostgreSQL tests for each schema and migration history.
- Test each area's domain invariants, repositories, service workflows, context
  snapshots, and Streamlit interactions independently.
- Verify there are no imports, foreign keys, queries, identifiers, prompts, or
  runtime initialization paths crossing between Chat and Characters.
- Add observability for generation, summarization, extraction, relationship
  validation, strategy execution, and context assembly failures.
- Verify export and deletion within each area's independent ownership boundary.
- Prove that Characters services, migrations, and tests run without initializing
  Chat, then document the remaining deployment packaging work.

**Complete when:** the full quality suite passes, each area can be operated and
tested independently, and separating Characters requires packaging and
deployment work rather than domain or data redesign.

## Initial delivery milestone

Implement Stages 1–3 first:

> Chat runs from its own bounded module and PostgreSQL schema, supports durable
> conversations through provider-neutral local and cloud adapters, and manages
> conversation summaries and user-controlled Chat-wide memory without any
> Characters dependency.

Begin Characters implementation only after the schema and import-isolation checks
for this milestone pass.

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
unit tests beside the affected area and integration tests whenever a change
crosses service and repository boundaries.
