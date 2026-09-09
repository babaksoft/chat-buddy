# Chat Buddy Design

Status: Initial design, living document  
Last updated: 2026-09-09

## Purpose

Chat Buddy is a local-first application for maintaining persona conversations with
clear identity, continuity, memory, time, and relationship boundaries. The user
should always be able to predict which identity the persona is interacting with,
what prior information is available, and whether an action changes the current
conversation or creates an alternate branch.

This document is the current product and architecture source of truth. When a
design decision changes, update this document in the same change that implements
or plans the decision.

## Core hierarchy

The primary navigation and ownership hierarchy is:

```text
You / Identity
└── Persona
    ├── Ongoing chat
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
        ├── Mode: Chat | Storyline | Timeline
        ├── Conversations, scenes, or days
        ├── Relationship state and events
        ├── Memories
        └── Persona adaptation
```

Information does not cross continuity boundaries unless a future feature makes
that transfer explicit to the user.

## Identity

An identity describes who the user is within a continuity. The application has a
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

## Persona

The global persona definition contains authored, long-term traits and is
immutable. Editing a persona initially means duplicating it into a new persona.

Persona behavior is divided into three layers:

1. **Persona core:** stable authored definition shared wherever that persona is
   selected.
2. **Relationship adaptation:** continuity-specific knowledge, habits, feelings,
   and behavior toward the selected identity.
3. **Current state:** temporary scene, mood, and immediate conversational context.

Conversation-driven evolution never silently mutates the persona core or affects
another identity or continuity.

## Continuity modes

Every continuity has exactly one mode.

### Chat

Chat is one ongoing conversation for an identity/persona pair.

- There is at most one active Chat for an identity/persona pair; previous Chats
  may be archived.
- The selected conversation branch is the primary context.
- No long-term memories are extracted.
- Long conversations may use a rolling summary for context compression. This is
  part of the Chat context, not extracted memory.
- Relationship development is local to the Chat and does not carry into another
  mode or continuity.
- The persona begins with its core traits and the explicitly selected starting
  relationship.

### Storyline

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

### Timeline

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

## Scene setup and response style

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

## Conversation branches and retries

Messages are immutable and conversations support alternate paths.

- **Branch from here** creates a new path without deleting the existing future.
- A conversation has a selected branch; only that path is included in model
  context.
- Retrying the last persona response creates an alternate response to the same
  user message.
- Retry allowance is limited and shown in the UI. The initial proposed limit is
  three retries per persona turn.
- Only the selected response variant contributes to future memory or relationship
  evolution.
- Chat can branch within its continuity.
- The current/latest Storyline scene can branch in place; changing an older scene
  with dependent scenes forks the Storyline.
- The current Timeline day can branch; a closed day requires a Timeline fork.

## Memory

Memories belong to a continuity and include provenance. A memory records its
source, when its subject occurred, when it was learned, and whether it is active,
superseded, excluded, or deleted.

A memory is eligible for model context only when:

- It belongs to the current continuity.
- It belongs to the selected branch or an applicable ancestor.
- Its effective time is not later than the current scene or Timeline day.
- It is active and not excluded.

Memory extraction occurs only after a complete turn and includes both the user
message and the selected persona response.

Users can:

- Inspect a memory and its source.
- Correct it by superseding the extracted interpretation.
- Exclude it from future prompts.
- Permanently delete it for privacy.

Closed transcripts may remain historically immutable while their extracted
interpretations remain correctable. Narrative integrity must not prevent users
from deleting their own data.

## Relationship model

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

### Relationship intent

When creating a continuity, the user may choose:

- Platonic.
- Open to romance.
- Established relationship.
- Let it develop naturally.

The user can freely select an established starting state. This records the state
as user-selected but does not invent a synthetic background or specific shared
events.

### Evolution and milestones

- Familiarity, trust, affection, and the current dynamic can evolve gradually.
- Status changes use conservative thresholds and hysteresis rather than reacting
  to a single message.
- The UI presents qualitative labels, not experience points or progress bars.
- Major romantic milestones such as partnership, engagement, marriage, breakup,
  and reconciliation require an explicit narrative event.
- A temporary conflict changes the current dynamic; it does not automatically
  erase an established status.
- Relationship changes have inspectable provenance and can be corrected by the
  user.
- Model-generated relationship proposals are validated against relationship
  intent and domain transition rules before persistence.

## Context composition

Model context is assembled in a stable order:

```text
Persona core
→ Identity
→ Relationship intent and state
→ Eligible memories
→ Scene setup and current state
→ Response style
→ Conversation summary and recent selected-branch messages
```

Each mode provides its own context eligibility policy. Token budgeting and
conversation summarization remain separate from decisions about which memory or
relationship information is permitted.

## UX principles

- Make the active identity, persona, continuity, and mode visible.
- Explain what will carry forward before a continuity begins.
- Prefer archives and branches over destructive history changes.
- Never leak state across identities or continuities.
- Show the source of inferred memory and relationship information.
- Preserve user control over stored personal information.
- Do not fabricate missing Timeline days or unspecified relationship history.
- Keep model limitations and recoverable generation failures visible rather than
  silently corrupting conversation state.

## Deferred decisions

The following details will be refined when their implementation stage begins:

- Exact response-style controls and defaults.
- Whether cosmetic fields on a frozen identity remain editable.
- The complete vocabulary for current relationship dynamics.
- Memory categories, confidence, and review workflow.
- Branch visualization and naming.
- Archival and duplication UX for continuities and personas.
