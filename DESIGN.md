# Chat Buddy Design

Status: Living design

Last updated: 2026-09-19

## Purpose

Chat Buddy is a local-first application shell containing two product areas with
distinct, non-overlapping purposes:

- **Chat** provides persistent conversations with local and cloud LLMs. It owns
  conversation history, automatic context management, rolling summaries, and
  extracted user memory.
- **Characters** maintains user identities, LLM personas, and continuities
  between them. It is the only area where persona and relationship evolution is
  researched, evaluated, and delivered as a product feature.

The areas initially share a repository, process, and architectural style to make
experimentation convenient. Characters is expected to become a standalone
application, so convenience must not create domain or persistence coupling.

This document is the current product and architecture source of truth. When a
design decision changes, update this document in the same change that implements
or plans the decision.

## Application boundaries

The application is a thin shell around two bounded areas:

```text
Chat Buddy shell
├── Chat
│   ├── Conversations and messages
│   ├── LLM provider selection
│   ├── Context budgeting and summaries
│   └── Chat-wide extracted memory
└── Characters
    ├── Identities and personas
    ├── Continuities and conversations
    ├── Relationship and persona evolution
    └── Ongoing, Storyline, and Timeline modes
```

Each area follows the same inward-facing architecture with its own domain,
application, infrastructure, prompts, persistence, and UI modules. Domain models,
repository and gateway protocols, services, prompts, database models, and stored
records belong to exactly one area.

The shell may share generic configuration, logging, and low-level provider
utilities. Shared code must not contain area-specific business rules or become an
integration path between the areas. Each area owns its own LLM gateway contracts,
even when adapters use the same low-level client utility.

Chat and Characters do not import each other's modules, read each other's
tables, or exchange records at runtime. There is no implicit identity, persona,
continuity, or memory relationship between them.

## Persistence boundaries

One PostgreSQL database initially hosts two independent named schemas:

- `chat` contains only Chat records.
- `characters` contains only Characters records.

Each schema has independent SQLAlchemy metadata, declarative models, repository
implementations, migration history, and Alembic version table. Cross-schema
foreign keys, joins, and repository queries are prohibited. The schemas do not
need to use compatible identifiers, structures, lifecycle rules, or migration
schedules.

The first split establishes clean schema baselines. Existing development data is
disposable and is not transformed into the new schemas. Previously applied
migration files remain unchanged as historical records, and developers recreate
their local database when the new baselines are introduced.

This boundary lets Characters move to another database or deployment without a
data migration or compatibility layer for Chat.

## Chat area

Chat is a general-purpose assistant experience. It does not model identities,
personas, relationships, or continuities from the Characters area.

The Stage 3 Chat design supersedes the earlier prototype behavior. The prototype
database schema is only a structural starting point: its old test data has been
deleted, and the redesign has no legacy-row preservation or conversion
requirement. Applied migrations remain historical records; new schema work uses
new Chat migrations.

### Conversations and providers

- Conversations and messages persist and can be resumed independently.
- A conversation records the provider, model, and generation configuration used
  for its responses.
- Provider selection supports local and cloud LLMs through a Chat-owned gateway
  protocol.
- Ollama remains the initial local adapter. Cloud providers are added as
  independent adapters without changing conversation or context services.
- Streaming failures remain visible and recoverable without leaving an ambiguous
  half-turn.

Chat conversations are linear. A conversation has at most one pending or
streaming generation attempt and cannot accept a new user message while its
final user message lacks a completed assistant response. Only the latest failed
or interrupted attempt for that unmatched tail is retryable; older terminal
attempts remain history rather than alternate response branches.

The unmatched tail may be edited while no attempt is open and then retried later.
Each attempt stores the exact submitted user-content snapshot, so editing the
visible tail does not rewrite earlier attempt history. A successful retry creates
one assistant message, closes the turn, and restores the conversation to its
normal ready state.

### Context management and summaries

Chat assembles context through separate eligibility, rolling-summary, and token-
budgeting services. Eligible inputs are active Chat memory, the current
conversation's active summary, complete turns not already covered by that
summary, and the current user input. Incomplete attempts and partial output are
never eligible.

Each selected model provides a context-window limit, token counter, and default
output reserve. Prompt capacity subtracts both fixed prompt overhead and the
effective output reserve from the context window. Mandatory current input, the
active summary, and the configured minimum recent turns must fit without
arbitrary text truncation. Active memories and additional turns are admitted in
deterministic priority order while capacity remains.

When eligible context reaches its configured threshold, older complete turns
are compressed into a rolling summary. Summaries are versioned: one version is
active, replacements supersede it, and provenance identifies the predecessor
and last covered assistant-message checkpoint. ADR 016's linear turn invariant
makes that checkpoint authoritative; a conversation cannot complete an older
turn after advancing to newer turns. A summary belongs only to its conversation,
is deleted with that conversation, and never becomes memory merely because it
was summarized. An oversized active summary may be recompacted for a smaller
selected model without advancing its checkpoint.

Summary failure preserves the last durable summary. Chat may omit optional
inputs, but it fails before creating a generation attempt or calling a response
provider when mandatory context cannot fit. ADR 017 defines eligibility and
budgeting; ADR 018 defines summary ownership, lineage, and failure behavior.

### Extracted memory

Chat memory captures durable user information that may help across Chat
conversations. It belongs to the Chat area rather than to one conversation or to
a Characters identity. Each logical memory has a stable identity and subject and
retains provenance-aware revisions.

Persisted memory revisions are active, excluded, or superseded. Only a current
active revision is context-eligible. Correction creates a user-authored revision
and atomically supersedes the prior one; later extraction cannot overwrite that
correction. Exclusion is reversible and cannot be undone by extraction. Hard
deletion purges the complete logical memory and its provenance, so `deleted` is a
terminal domain result rather than a retained tombstone.

Extracted provenance identifies the source conversation, complete user/assistant
turn, and completed generation attempt. Extraction runs only after the assistant
message commits and makes at most three processing attempts. Success, including
an empty result, or retry exhaustion creates a terminal attempt-level receipt so
later callbacks do not repeat the work. Exhaustion is logged and never changes
the completed response. The receipt stores no candidate content and no
per-memory effect graph.

The prior prototype key/value shape supplies no legacy records to the new model.
If a source conversation is deleted, the Chat-wide memory remains but its
provenance states that the source is no longer available; memory deletion is a
separate user action. ADR 019 defines memory lifecycle and user control, while
ADR 020 defines bounded completed-turn extraction and conflict handling.

Chat memory never enters Characters context, and Characters memories or
relationship state never enter Chat context.

## Characters area

Characters maintains authored user identities, LLM personas, and coherent
versions of the relationship between them. It also provides an isolated place to
experiment with persona and relationship evolution strategies. A strategy is
versioned and evaluated inside Characters; a finalized strategy is delivered only
as a Characters feature.

### Core hierarchy

The primary navigation and ownership hierarchy is:

```text
You / Identity
└── Persona
    ├── Ongoing continuity
    ├── Storyline: Main
    │   ├── First encounter
    │   └── Dinner at the restaurant
    └── Timeline
```

A **continuity** represents one coherent version of an identity/persona
relationship. It owns the conversations, eligible memories, relationship state,
and persona adaptation that occur within that version of the relationship.

```text
Identity
└── Persona
    └── Continuity
        ├── Mode: Ongoing | Storyline | Timeline
        ├── Conversations, scenes, or days
        ├── Relationship state and events
        ├── Memories
        └── Persona adaptation
```

Information does not cross continuity boundaries unless a future Characters
feature makes that transfer explicit to the user.

### Identity

An identity describes who the user is within a continuity. Characters has a
default identity, shown as **You**, and may have additional identities.

Initial identity attributes are:

- Name.
- Optional gender.
- Age or birth date.
- Optional pronouns or preferred form of address.
- Local IANA timezone where time-based behavior is needed.

An identity may be created inline while starting a continuity. It remains
editable until its first continuity begins, at which point it is frozen. To use
different semantic identity details afterward, the user duplicates or creates
another identity. Cosmetic changes may be distinguished from semantic changes in
a later design.

A continuity cannot switch identity after it begins.

### Persona

The global persona definition contains authored, long-term traits and is
immutable. Editing a persona initially means duplicating it into a new persona.

Persona behavior is divided into three layers:

1. **Persona core:** stable authored definition shared wherever that persona is
   selected inside Characters.
2. **Relationship adaptation:** continuity-specific knowledge, habits, feelings,
   and behavior toward the selected identity.
3. **Current state:** temporary scene, mood, and immediate conversational context.

Conversation-driven evolution never silently mutates the persona core or affects
another identity or continuity.

### Continuity modes

Every continuity has exactly one mode.

#### Ongoing

Ongoing is one continuous character conversation for an identity/persona pair.
The name distinguishes this mode from the top-level Chat area.

- There is at most one active Ongoing continuity for an identity/persona pair;
  previous ones may be archived.
- The selected conversation branch is the primary context.
- No long-term memories are extracted.
- Long conversations may use a rolling summary for context compression. This is
  part of the Ongoing context, not extracted memory.
- Relationship development is local to the continuity and does not carry into
  another mode or continuity.
- The persona begins with its core traits and the explicitly selected starting
  relationship.

#### Storyline

A Storyline is an ordered sequence of narrative scenes. An identity/persona pair
may have multiple named Storylines.

- A scene starts with an initial setup, which also supplies its default title.
- Scene titles can be edited independently from their setup.
- A scene's chronological position becomes immutable when interaction begins.
- Memory is extracted from completed turns.
- A scene can use active memories from itself and earlier scenes in the same
  Storyline, but never memories from later scenes.
- Later scenes receive eligible memories and relationship state, not necessarily
  raw earlier transcripts.
- Persona adaptation and relationship state evolve across the Storyline.
- Branching an older scene when later scenes exist forks the Storyline so the
  existing future remains intact.

#### Timeline

A Timeline models an ongoing relationship as calendar-day conversations.

- There is at most one active Timeline for an identity/persona pair.
- Each conversation has a visible, read-only local date.
- There is at most one conversation per local date.
- Days without interaction are absent; the application never fabricates empty
  conversations.
- The current local day is writable. Once its day boundary passes, it is closed
  and read-only.
- Current-day messages provide short-term context. Eligible memories and
  relationship state from previous days provide long-term context.
- The Timeline stores an IANA timezone. A timezone change affects future day
  boundaries rather than rewriting existing local dates.
- If the application is offline at midnight, it closes the previous day when it
  next runs.
- A closed day cannot be retried or edited inside the same Timeline. An alternate
  past requires forking the Timeline into a new continuity.

### Scene setup and response style

Scene setup and response presentation are separate concepts.

**Scene setup** describes the initial place, situation, time, and mood. It evolves
naturally through conversation.

**Response style** controls presentation, including whether the persona describes
scenes, gestures, or emotions before or after dialogue. Planned controls include:

- Description level: none, light, or immersive.
- Response length: concise, balanced, or detailed.
- Narrative placement: before, after, or both.
- Dialogue formatting and tone.

Style can change at a message boundary. The change affects subsequent persona
responses but does not alter facts, memories, relationship state, or prior
messages. The style used to generate a persona message is recorded with it.

### Conversation branches and retries

Messages are immutable and character conversations support alternate paths.

- **Branch from here** creates a new path without deleting the existing future.
- A conversation has a selected branch; only that path is included in model
  context.
- Retrying the last persona response creates an alternate response to the same
  user message.
- Retry allowance is limited and shown in the UI. The initial limit is three
  retries per persona turn.
- Only the selected response variant contributes to future memory or relationship
  evolution.
- Ongoing branches within its continuity.
- The current/latest Storyline scene can branch in place; changing an older scene
  with dependent scenes forks the Storyline.
- The current Timeline day can branch; a closed day requires a Timeline fork.

### Memory

Characters memories belong to a continuity and include provenance. A memory
records its source, when its subject occurred, when it was learned, and whether
it is active, superseded, excluded, or deleted.

A memory is eligible for model context only when:

- It belongs to the current continuity.
- It belongs to the selected branch or an applicable ancestor.
- Its effective time is not later than the current scene or Timeline day.
- It is active and not excluded.

Memory extraction occurs only after a complete turn and includes both the user
message and the selected persona response.

Users can inspect a memory and its source, correct it by superseding the extracted
interpretation, exclude it from future prompts, and permanently delete it for
privacy. Closed transcripts may remain historically immutable while their
extracted interpretations remain correctable.

### Relationship model

Relationship state belongs to:

> identity + persona + continuity

The relationship is multidimensional rather than a single score.

- **Social status:** stranger, acquaintance, casual friend, or close friend.
- **Romantic status:** none, interest, dating, partner, engaged, or spouse.
- **Current dynamic:** for example neutral, comfortable, affectionate, awkward,
  tense, or estranged.
- **Supporting dimensions:** qualitative familiarity, trust, and affection.
- **Milestones and boundaries:** explicit events with provenance.

Friendship and romance are related but independent tracks. Close friendship does
not automatically become romantic, and a romantic partnership does not require a
particular friendship label.

When creating a continuity, the user may choose platonic, open to romance,
established relationship, or let it develop naturally. An established starting
state is recorded as user-selected and does not invent background events.

Familiarity, trust, affection, and the current dynamic can evolve gradually.
Status changes use conservative thresholds and hysteresis. Major romantic
milestones require an explicit narrative event. Model-generated proposals are
validated against relationship intent and domain transition rules before
persistence, and every accepted change has inspectable provenance and can be
corrected by the user.

### Context composition

Characters context is assembled in a stable order:

```text
Persona core
→ Identity
→ Relationship intent and state
→ Eligible continuity memories
→ Scene setup and current state
→ Response style
→ Conversation summary and recent selected-branch messages
```

Each mode provides its own context eligibility policy. Token budgeting and
conversation summarization remain separate from decisions about which memory or
relationship information is permitted.

## Evolution experiments

Persona and relationship evolution strategies are Characters-owned application
interfaces. Experimental implementations must:

- Record a stable strategy name and version with generated proposals or derived
  state.
- Operate only on Characters-owned inputs and records.
- Pass domain validation before changing durable state.
- Remain replaceable without changing Chat or the shared shell.

Experiments may be compared within Characters. Promotion makes a strategy an
available or default Characters behavior; it never adds persona evolution to the
Chat area.

## UX principles

- Make the selected product area unmistakable.
- In Chat, expose the active model and make summaries and extracted memory
  inspectable.
- In Characters, make the active identity, persona, continuity, and mode visible.
- Explain what carries forward before a Characters continuity begins.
- Prefer archives and branches over destructive history changes.
- Never leak records across areas, identities, or continuities.
- Show the source of inferred memory and relationship information.
- Preserve user control over stored personal information.
- Keep model limitations and recoverable generation failures visible.

## Characters extraction criteria

Characters is ready to become a standalone application when:

- Its code has no imports from Chat.
- Its schema has no foreign keys, queries, identifiers, or migrations tied to
  Chat.
- Its application services can be composed without initializing Chat services.
- Shared technical utilities can be copied or packaged without carrying Chat
  business behavior.
- Its tests and migration history can run independently.

## Deferred decisions

The following details will be refined when their implementation stage begins:

- Specific cloud LLM vendors and authentication configuration.
- Exact response-style controls and defaults.
- Whether cosmetic fields on a frozen identity remain editable.
- The complete vocabulary for current relationship dynamics.
- Memory categories, confidence, and review workflow in each area.
- Branch visualization and naming.
- Archival and duplication UX for Characters continuities and personas.
