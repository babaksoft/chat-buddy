# Chat Buddy Design

Status: Living design

Last updated: 2026-10-28

## Purpose and scope

Chat Buddy is a local-first application containing two independent product areas:

- **Chat** provides persistent general-purpose conversations, provider selection,
  automatic context management, rolling summaries, and user-controlled memory.
- **Characters** provides authored identities and personas, isolated relationship
  continuities, narrative conversation modes, and versioned persona and
  relationship evolution.

This document defines the intended product behavior, domain model, ownership
boundaries, and architectural constraints. It describes the design that
implementation must converge on, whether or not every capability is currently
delivered.

This document does not track delivery status, implementation slices, setup
instructions, migration revision history, or method-level APIs. Those concerns
belong to the execution plans, README, migrations, and source documentation.

## Design goals and constraints

The design optimizes for:

- Local-first operation with explicit opt-in to external providers.
- Durable, resumable conversations with visible recovery from partial failure.
- User control over inferred personal information.
- Strict isolation between Chat and Characters.
- Strict isolation among Characters identities, personas, and continuities.
- Explainable derived state with source provenance.
- Provider-neutral application behavior.
- Safe experimentation with replaceable, versioned Characters strategies.
- Eventual extraction of Characters into an independent application.

The following constraints are mandatory:

- Chat and Characters do not import each other or exchange runtime records.
- Business rules, prompts, provider contracts, repositories, and persistence
  models belong to exactly one area.
- Shared code contains only generic configuration, logging, and low-level
  technical utilities.
- Services and UI code do not issue direct database queries.
- Completed messages and provenance records are immutable.
- Context includes only records eligible for the current area, owner, continuity,
  branch, and time.
- External calls do not hold database transactions open.

Chat is not a character simulation system. It does not acquire Characters
identities, personas, continuities, relationship state, or persona evolution.
Characters does not reuse Chat conversations, summaries, or memories.

## System context

```text
User
  |
  v
Streamlit shell
  ├── Chat
  │   ├── Chat application and domain
  │   ├── Local or cloud response provider
  │   └── PostgreSQL chat schema
  └── Characters
      ├── Characters application and domain
      ├── Local or future approved response provider
      └── PostgreSQL characters schema
```

The user interacts through one Streamlit shell and explicitly selects Chat or
Characters. The shell routes requests but owns no product behavior.

PostgreSQL is the durable system of record. Ollama supplies local model access.
Approved cloud providers may supply selected capabilities after explicit
configuration. Provider clients, endpoints, authentication, and SDK-specific
behavior remain outside the domain and application layers.

The principal trust boundaries are:

- The browser and Streamlit process.
- The application and PostgreSQL.
- The application and each configured model provider.
- The permanent ownership boundary between Chat and Characters.

## Architecture and dependency rules

The repository is organized around two bounded areas:

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

Within each area, dependencies point inward:

```text
UI ───────┐
          v
Infrastructure → Application → Domain
          |
          └── implements domain-owned repository and gateway contracts
```

The layers have the following responsibilities:

- **Domain** owns immutable values, invariants, errors, and repository or gateway
  protocols.
- **Application** owns workflows, eligibility policy, context assembly, token
  budgeting, and transaction-independent orchestration.
- **Infrastructure** owns SQLAlchemy models and repositories, provider adapters,
  configuration, and composition.
- **Prompts** owns area-specific prompt templates and formatting.
- **UI** renders application results and invokes application services.
- **Composition root** selects an area and constructs only that area's runtime
  dependencies.

The shell may import both UI areas. No other Chat-to-Characters or
Characters-to-Chat dependency is permitted. Cross-schema foreign keys, joins,
queries, identifiers, and repository operations are prohibited.

Characters strategy interfaces are application extension points. Implementations
receive immutable Characters-owned inputs, produce structured proposals, and
identify themselves with a stable name and version. A strategy cannot mutate
repositories directly or introduce behavior into Chat.

Characters must remain separable: its services, migrations, tests, provider
composition, and UI behavior must operate without importing or initializing Chat.

## Domain model and invariants

### Chat

A Chat conversation owns its messages, generation attempts, requested provider
selection, and rolling-summary lineage. Chat memories are Chat-wide and may be
eligible across conversations, but retain source provenance.

Chat conversations are linear:

- Messages form complete user/assistant turns.
- At most one generation attempt is pending or streaming per conversation.
- A new user message is rejected while the conversation has an unmatched user
  tail.
- Failed and interrupted output remains attempt evidence outside committed
  history.
- Retrying an incomplete turn reuses its user message and cannot create multiple
  completed assistant responses.
- Each completed response retains the effective provider, model, generation
  configuration, and attempt provenance.

A rolling summary belongs to one conversation. Revisions are immutable and record
their predecessor and last covered assistant-message checkpoint. Exactly one
revision is current. A summary is context compression, not extracted memory.

A logical Chat memory has a stable identity, subject, revision lineage, lifecycle,
and source provenance:

- Only the current active revision is context-eligible.
- Correction creates a user-authored revision and supersedes the prior revision.
- Exclusion is reversible and cannot be undone by later extraction.
- Hard deletion removes the complete memory lineage and provenance.
- Deleting a source conversation does not implicitly delete reusable memory; its
  provenance instead reports that the source is unavailable.

### Characters

The Characters ownership hierarchy is:

```text
Identity + Persona
└── Continuity
    ├── Mode
    ├── Conversations, scenes, or days
    ├── Selected conversation branches
    ├── Continuity memories
    ├── Relationship state and events
    └── Persona adaptation
```

Identities and personas are independently authored profiles. A continuity binds
one of each; neither profile owns the other.

An **identity** describes who the user is inside Characters. A default identity is
shown as **You**. Authored identity details are editable until first continuity
use. Starting that continuity permanently freezes the identity. Later semantic
changes require a new or duplicated identity. A continuity cannot change identity.

A **persona** has three conceptual layers:

1. **Persona core** — authored long-term definition and traits.
2. **Persona adaptation** — durable continuity-specific behavior toward one
   identity, such as communication, openness, support, conflict, and shared-habit
   preferences.
3. **Current state** — temporary scene, mood, and immediate context.

The persona core is editable until its first continuity use, then freezes globally
and permanently. Later authored changes require a new or duplicated persona.
Conversation-driven behavior never silently modifies the core.

Starting a continuity:

- Permanently binds one identity, one persona, and one mode.
- Verifies the reviewed revisions of both profiles.
- Freezes newly used profiles in the same transaction that creates the continuity.
- Creates an independent starting relationship without invented shared events.
- Is idempotent for an identical confirmation and rejects conflicting reuse.
- Does not transfer conversation, memory, relationship, or adaptation state from
  another continuity unless it is the explicit remapped Storyline fork below.

A confirmed Storyline start also supplies its user-authored name and initial
scene. The initial scene owns a title, setup, fixed response-style snapshot,
conversation graph, and summary lineage. All confirmed fields participate in
idempotency. An identity/persona pair may own at most one active Storyline. Archival
leaves its scenes and memory read-only but permits a fresh, independent Storyline
with a new confirmation and starting relationship. The same pair may independently
own an Ongoing continuity.

Archiving a continuity is explicit and makes it permanently read-only. It does not
unfreeze profiles or create a replacement.

### Continuity modes

Every continuity has exactly one mode:

- **Ongoing** is one continuous conversation. At most one Ongoing continuity is
  active for an identity/persona pair. It uses rolling summaries and does not
  extract long-term memory.
- **Storyline** is a named, chronologically ordered sequence of named scenes. Its
  initial scene is created with the continuity. The latest scene is the only
  normally writable scene; after it has a complete exchange and no incomplete
  attempt, the user may resume it or append one next scene. Scenes cannot be
  pre-created, inserted, or reordered, so at most the latest scene is empty. Each
  scene's setup freezes on its own first user message; its title remains editable
  presentation metadata and never enters a prompt. A scene may use eligible
  memories from itself and earlier scenes, never from later scenes.
- **Timeline** is a sequence of untitled local-calendar-day scenes. It has at most
  one conversation per represented date, creates a day with its first user input
  and attempt rather than as a placeholder, and keeps resolved historical dates
  immutable.

Timeline closure uses the continuity's IANA timezone. The current local day is
writable; a past day is closed and read-only, including when closure is first
detected after an offline period. Timezone changes affect future boundaries only.

### Branches and alternatives

Characters messages are immutable nodes with parent-message relationships. A
conversation records one selected leaf, and only its root-to-leaf path is eligible
for context and downstream derivation.

- Root children are user messages, roles alternate on every edge, and parent
  traversal defines path order without a persisted sequence or depth.
- Selected-path reads are separate from graph inspection. Selection and append
  compare the caller's expected leaf so stale actions cannot replace the active
  path.
- Branching from any exact owned persona message preserves every existing future.
- Retrying a completed persona response creates a sibling response to the same
  user message; failed or interrupted attempts create no node and consume no retry.
- A persona turn permits at most three retry alternatives in addition to its
  initial response.
- Selecting an alternative changes future context without deleting other paths.
- Only selected messages can contribute to summaries, memory, relationship state,
  or persona adaptation.
- Ongoing branches in place.
- Branching from a Storyline scene with dependent later scenes forks the Storyline;
  retry and saved-future selection require a writable scene and never fork.
- Because a Storyline fork preserves the active source while creating another
  active future, it creates a distinct pair by exactly duplicating at least one
  source profile. The target pair must not already own a Storyline. The fork copies
  ordered metadata and selected histories for earlier scenes, then the chosen
  scene's ancestry through the exact persona branch point. It assigns new
  continuity-owned identifiers, remaps compatible summary and completed-attempt
  provenance, excludes later scenes and nodes outside the copied ancestries, and
  changes only the fork.
- A closed Timeline day cannot retry or branch in place; an alternate past requires
  a Timeline fork.

Persona messages retain their effective response style, provider, model,
generation metadata and budget, strategy version, and completing attempt. Summary
revisions retain predecessor and persona-checkpoint references; the current summary
is the deepest compatible checkpoint on the selected ancestry rather than a
conversation-wide active row.

### Characters memory and relationship state

Storyline memory belongs to one continuity. A logical fact has a stable identity
and an immutable revision lineage. Exactly one revision is current and active or
excluded; older revisions are superseded. Extraction creates an active revision,
reinforcement adds distinct evidence without changing the revision, and an
unambiguous automatic change may supersede only an active extracted revision.
User correction may change subject and content, creates a user-authored active
revision, and preserves the corrected revision's source and temporal provenance.
Exclusion and reactivation each create a revision while retaining content and
provenance; an excluded memory must be reactivated before correction. Every
management change names the expected current revision. Hard deletion removes the
complete lineage, evidence, and associated conflicts without a tombstone.

Every extracted revision and reinforcement identifies its source scene, complete
selected turn, persona-message checkpoint, extraction configuration, and creation
time. Occurrence position is the ordered scene where the asserted event or state
occurred. Learned position is the source scene where the persona learned it, and
cannot precede occurrence. Both use immutable scene order for comparison. A
memory is eligible only when it:

- Belongs to the current continuity.
- Comes from the selected branch or an applicable ancestor.
- Has current-content source evidence on the selected ancestry.
- Has occurrence and learned positions no later than the target scene.
- Is active and not excluded.

Extraction occurs only after a complete selected turn. Users can inspect, correct,
exclude, reactivate, and permanently delete extracted interpretations. Switching
away from the current revision's source branch makes it ineligible without
deleting it; switching back restores eligibility. A deselected reinforcement does
not invalidate content whose originating evidence remains selected. Lifecycle and
correction changes affect the next assembled response context; they do not rewrite
prior prompts or messages.

An explicit Storyline fork may copy an eligible active lineage only when its
originating evidence is on the copied selected histories. The fork remaps copied
source and temporal provenance into a new independent lineage owned by the fork's
distinct profile pair and copies only supporting evidence whose source was also
copied. Excluded or future memory and unresolved conflicts do not cross the fork.
No continuity-owned row is shared.

Stage 6 provides no source-scene, conversation, or message deletion. Any future
source-deletion workflow must reject deletion while memory provenance refers to
the source. Archival preserves those records. Hard deletion of a logical memory
removes its own provenance but does not delete its sources.

Relationship state belongs to one identity, persona, and continuity. It is the
durable relationship between the identity and persona and separates:

- Social status.
- Romantic status.
- Current interaction dynamic.
- Qualitative supporting dimensions such as trust and affection.
- Provenance-backed milestones.

Friendship and romance are independent tracks. Supporting dimensions do not imply
a status or shared event. Established starting states are explicitly user-selected.
Major romantic transitions require narrative evidence. Gradual changes use
conservative thresholds and hysteresis.

Persona adaptation is durable continuity-specific behavior toward the identity.
It specializes expression of the persona core but cannot contradict or modify it.
Memory instead records declarative facts and past events. One turn may support
both memory and adaptation, but each has independent eligibility, validation,
persistence, and correction. Current state remains temporary mood, scene,
activity, and immediate context; prompt inclusion does not make it durable.

User-selected relationship intent and boundaries constrain evolution rather than
acting as inferred relationship dimensions. Automated evolution cannot remove or
weaken a boundary, and platonic intent prohibits romantic evolution.

Evolution uses the following durable vocabulary:

- Evidence is an exact eligible source turn or checkpoint on selected history.
- A proposal is a bounded atomic set of typed changes from a versioned strategy.
- A decision is the application's apply, reject, or no-change validation result.
- An event is an immutable accepted relationship or adaptation change, including
  a user correction.
- An effect idempotently processes one source persona checkpoint and records its
  terminal decision and exact strategy configuration.
- A projection is a rebuildable current view derived by replaying eligible events
  from the user-selected starting state.

Strategies propose changes; they do not write state directly. The application
validates ownership, selected evidence, expected projection revision, relationship
intent, boundaries, persona-core compatibility, transition rules, conservative
thresholds, and proposal bounds. It applies a proposal atomically or rejects it in
full. Accepted events are append-only and authoritative; projections are caches.
A correction appends a user-authored event rather than rewriting an inference or
conversation history.

Ownership, evidence, replay, user authority, persona-core immutability, bounded
atomic application, and milestone requirements are stable invariants. Evidence
selection, prompts, providers, strategies, adaptation facets, gradual thresholds,
and evaluation rubrics are versioned experimental surfaces and cannot relax those
invariants. Each effect records the exact selector, strategy, policy,
prompt-schema, provider, and model versions.

## Behavioral design

### Chat response generation

1. The user submits or retries the sole unmatched user message.
2. The application resolves the selected provider and immutable effective
   generation configuration.
3. Context eligibility and token budgeting complete before an attempt is reserved.
4. The repository atomically records the user input when needed and a pending
   generation attempt.
5. The provider streams outside the transaction; partial output is saved only on
   the attempt.
6. Successful completion atomically appends one assistant message and completes
   the attempt.
7. Failure or interruption preserves recoverable attempt evidence without adding
   partial output to conversation history.

Title generation, summarization, and memory extraction are separate capabilities.
A visible response can succeed even if later utility processing fails.

### Chat context and memory

Chat context is assembled from active Chat memories, the active conversation
summary, complete uncovered turns, and current input. Partial attempts are never
eligible. Mandatory context must fit after reserving fixed prompt overhead and
output capacity; otherwise generation fails before provider invocation.

Additional memories and turns are admitted in deterministic priority order. Older
complete turns are compressed into versioned rolling summaries when required.
Summary failure preserves the last durable revision and never silently omits
required context.

Memory extraction begins only after a complete turn commits. It is bounded and
idempotent per completed attempt. An empty extraction result and retry exhaustion
are terminal outcomes so callbacks cannot repeat processing indefinitely.

### Characters profile and continuity start

The user selects or authors an identity and persona, chooses a mode and starting
relationship, reviews the exact profile revisions and relationship values, and
confirms the start. Drafting, selection, review, and cancellation do not freeze
profiles. Confirmation performs profile verification, freezing, and continuity
creation atomically.

The starting relationship supports platonic, open-to-romance, established, and
natural-development intent. Established relationships require explicit compatible
social and romantic states. Boundaries cannot contradict the selected intent or
status. Every starting field records whether it was user-selected or defaulted.

### Characters response generation

Characters generation uses the same durable separation between committed messages
and incomplete attempt output. Every operation requires the complete identity,
persona, continuity, and conversation scope. Writes serialize with continuity
archival, so no message or response can commit after the continuity becomes
read-only.

Ongoing context is ordered as:

```text
Persona core
→ Identity
→ Starting relationship
→ Effective response presentation
→ Rolling summary
→ Recent selected-path messages
→ Current input
```

The general Characters context order, as later modes add state, is:

```text
Persona core
→ Identity
→ Relationship intent and current state
→ Eligible continuity memories
→ Scene setup and current state
→ Response style
→ Conversation summary and recent selected-path messages
```

Each mode owns its eligibility policy. Eligibility, token budgeting, summary
generation, and provider invocation remain separate responsibilities.

Storyline response context uses that general order with the scene's fixed response
style and only that scene's compatible summary and selected-path messages. Other
scene transcripts and titles are not short-term context. Response-memory selection
has its own budget and strategy version; optional memories never displace required
prompt blocks.

Ongoing summary revisions are continuity- and conversation-scoped. They cover only
complete selected turns and record their predecessor, checkpoint, effective
summary generation, and creation time. Unmatched user messages and incomplete
attempt output are excluded.

### Characters derivation and correction

After a complete selected turn, eligible modes may extract memory and ask the
configured versioned strategy for structured relationship or persona proposals.
The application validates and persists accepted effects with source provenance.

Storyline memory extraction has one retryable effect per source persona message.
It moves from reserved to terminal no-change or applied, cannot roll back the
visible turn, and cannot duplicate a terminal effect. Failures leave the same
effect retryable. Selection first builds an immutable, dedicated-budget snapshot
containing identity and persona labels, starting relationship, scene setup,
compatible summary, recent selected-path turns,
eligible memories, and the exact source turn marked as new evidence. Mandatory
ownership and source blocks must fit; optional records are selected whole and
deterministically. Extraction selection and response-memory selection remain
separate versioned strategies.

The versioned extractor returns no change or a bounded delta of create, reinforce,
supersede, and conflict operations. Each non-empty operation cites the exact new
source turn and can target only opaque current-memory identifiers supplied in the
snapshot. Prior context may disambiguate the new evidence but cannot independently
support a new assertion. The application rejects the entire delta for stale,
foreign, omitted, excluded, duplicate, contradictory, unsupported, or over-limit
operations. It alone may create a lineage, add unchanged evidence, supersede an
active extracted revision, or record a conflict. A conflict preserves the current
revision and its eligibility; proposed conflicting content never enters prompts.
Automatic extraction never supersedes user-authored memory.

Conflicts begin unresolved and retain proposed content, source evidence, and the
current revision observed during validation. Explicit dismissal against that
expected revision is their only state transition and keeps the current memory.
User correction remains a separate memory transition.

Extraction effects and derived memory record selector, extractor, and prompt
schema versions together with provider, model, effective configuration, source
checkpoint, and time. Selection, extraction, and later consolidation or ranking
may evolve independently without changing ownership, evidence, or temporal rules.

Changing the selected branch recomputes memory eligibility at read time without
rewriting its lineage. Derived relationship and persona projections rebuild from
eligible evidence when those capabilities are present. Unselected alternatives
cannot continue to influence context, memory, relationship projections, or persona
adaptation.

Relationship and adaptation evolution follows the same selected-history rule but
uses its own append-only events. A branch switch makes events supported only by
the deselected path inactive without deleting them and restores them if their
evidence becomes selected again. A reviewed Storyline fork copies only events
supported by copied history, remaps ownership and provenance, and then evolves
independently. A fresh continuity starts from its reviewed relationship and copies
no events, projection, memory, or adaptation.

Response style changes apply at a message boundary and affect only subsequent
persona responses. They never rewrite prior messages, facts, memories, or
relationship state.

## Data ownership and persistence

One PostgreSQL database may host both areas, but they remain logically independent:

- The `chat` schema contains only Chat records.
- The `characters` schema contains only Characters records.

Each schema owns separate SQLAlchemy metadata, declarative models, repositories,
migration history, and Alembic version table. The schemas do not require compatible
identifiers, structures, lifecycle rules, or migration schedules.

Repositories expose domain values rather than persistence models. Application
services use repositories for all durable reads and writes. Transactions are short
and enclose only state that must commit atomically.

Important transaction boundaries include:

- Reserving an attempt with any newly committed user input.
- Completing an attempt with its assistant or persona message.
- Freezing identity and persona profiles with continuity creation.
- Replacing a current summary revision.
- Correcting, excluding, reactivating, or deleting memory.
- Applying a validated relationship or persona proposal and its projection.
- Selecting a Characters branch or continuity fork.
- Applying one validated Storyline memory delta and its terminal extraction
  effect.

Optimistic revision checks reject stale authored edits and reviewed starts.
Database uniqueness and row locking enforce invariants that must survive concurrent
processes, including active-continuity limits, open-attempt limits, summary
replacement, active Storyline-pair uniqueness, archival races, and retry limits.

Derived records retain enough provenance to explain and rebuild their state.
Deletion respects ownership: deleting one area's record never queries or mutates
the other area.

## External interfaces and integrations

### Model providers

Each area owns narrow contracts for the capabilities it uses, such as streaming
responses, titles, summaries, memory extraction, model resolution, and token
counting. A provider need not implement every capability.

Provider adapters:

- Receive application-assembled prompts and immutable effective configuration.
- Keep endpoints, credentials, clients, and secrets outside domain values.
- Normalize SDK failures into area-owned errors.
- Release streams on completion, failure, or cancellation.
- Expose model capabilities, supported parameters, context limits, and output
  limits before invocation.

Ollama is the default local adapter. Chat may use explicitly enabled cloud adapters
for visible responses while retaining local utility operations. A cloud adapter
does not change Chat application or context services. Characters providers remain
independently configured and cannot reuse Chat contracts.

### Streamlit shell

The shell routes between product areas and preserves only presentation selection.
It does not share domain state. Each area UI invokes application services, displays
active ownership and provider scope, and never accesses provider SDKs or SQLAlchemy
directly.

### PostgreSQL

PostgreSQL supplies transactional persistence and concurrency enforcement. Each
area connects through its own session and repository composition and migrates only
its own schema.

## Cross-cutting concerns

### Security and privacy

- Provider credentials never enter prompts, domain snapshots, logs, or persisted
  generation configuration.
- Cloud use is explicit and communicates what eligible context leaves the local
  environment.
- Local correction or deletion cannot retract data already transmitted externally.
- Ownership checks include every required identifier rather than trusting a single
  record ID.
- Memory and inferred relationship information remain inspectable and controllable
  by the user.

### Reliability and recovery

- Provider calls occur outside database transactions.
- Pending, streaming, completed, failed, and interrupted attempts are explicit.
- Partial output never becomes committed history or derived evidence.
- Idempotency keys and expected revisions make repeated submissions safe.
- Timeouts or abandoned streams are reconciled before continuation.
- Late provider output is fenced after interruption, archival, selection change,
  or retry.
- Failures preserve the last valid durable state and expose a recovery action.

### Performance and capacity

- Every model declares a context window and output reserve.
- Context assembly accounts for provider framing and fixed prompt overhead.
- Required inputs are never silently truncated.
- Complete turns are selected deterministically and rendered chronologically.
- Summarization compresses older context without duplicating covered turns.
- Temporal and branch eligibility is decided before token budgeting.

### User experience and observability

- The active product area, provider/model, and relevant ownership scope are visible.
- Characters shows the selected identity, persona, continuity, and mode.
- Destructive actions require confirmation; archives and branches are preferred
  when history should remain recoverable.
- Incomplete output is visibly separate from committed history.
- Retry limits, read-only state, provider limitations, and recovery options are
  explicit.
- Inferred memory and relationship state links back to its source provenance.
- Generation, summarization, extraction, strategy, validation, and context failures
  are logged without leaking credentials or raw provider secrets.

## Related documents

- [README.md](README.md) — stable product overview, setup, configuration, and basic
  operation.
- [PLAN.md](PLAN.md) — implementation sequence, delivery status, and future work.
- [Decision records](docs/decisions/) — accepted behavioral decisions and their
  rationale.
- [AGENTS.md](AGENTS.md) — repository architecture, coding, testing, and
  documentation conventions.
- Stage plans under `work/` — implementation slices and verification for active
  or completed delivery work.
