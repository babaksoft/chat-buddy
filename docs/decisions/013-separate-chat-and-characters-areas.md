# ADR 013: Separate Chat and Characters into independent bounded areas

- Status: Accepted
- Date: 2026-09-15
- Clarifies: ADRs 006–011
- Supersedes: ADR 012

## Context

The original design treated general chat, user identities, personas,
continuities, relationship state, and persona evolution as one model. The product
now has two top-level areas with different purposes. Chat is a general persistent
LLM experience, while Characters owns identity/persona continuity and the
experimentation needed to evolve those relationships.

Characters will eventually become a standalone application. Sharing domain or
persistence models during the initial experimentation period would make that
separation expensive and would force two unrelated products to keep compatible
schemas.

The existing development data does not need to survive this design reset.

## Decision

Define Chat and Characters as independent bounded areas inside one temporary
application shell.

Chat owns conversations, messages, provider selection, automatic context
management, conversation summaries, and Chat-wide extracted memory. It does not
model or reference Characters identities, personas, relationships, or
continuities.

Characters owns identities, personas, continuities, character conversations,
continuity-scoped memory, relationship state, and persona-evolution strategies.
The Characters continuity mode previously named Chat is renamed **Ongoing** to
distinguish it from the top-level Chat area. ADRs 006–011 apply only to
Characters, with this terminology change.

Organize source code by area. Each area has its own domain, application,
infrastructure, prompts, persistence, and UI modules. The shell may share only
generic configuration, logging, and low-level provider utilities. Each area owns
its repository and LLM gateway protocols, services, prompts, and database models.
Neither area imports the other.

Use one PostgreSQL database with independent `chat` and `characters` schemas.
Give each schema separate SQLAlchemy metadata, migration history, and Alembic
version table. Do not create cross-schema foreign keys, joins, or repository
queries. The schemas do not need compatible structures or release schedules.

Establish clean schema baselines. Keep previously applied migration files
unchanged as historical records, require developers to recreate their local
database, and do not implement a legacy row-mapping or preservation path. This
supersedes ADR 012.

## Consequences

- Chat can evolve its provider, conversation, summary, and memory models without
  coordinating schema changes with Characters.
- Characters experiments and finalized persona-evolution features remain inside
  Characters and cannot affect general Chat behavior.
- Some low-level integration code may be shared, but area-specific contracts and
  orchestration may be intentionally duplicated.
- Running both areas initially requires two migration targets and two persistence
  compositions.
- Extracting Characters later requires packaging and deployment work rather than
  separating domain models or data.
- Existing pre-split development records are discarded when the new baselines
  are adopted.

## Alternatives considered

- Share identities and personas with Chat — not selected because the general
  assistant does not need character continuity and would become coupled to the
  future standalone application.
- Let Chat import finalized character snapshots — not selected because the areas
  currently have non-overlapping purposes and no transfer workflow is required.
- Keep one shared relational schema — not selected because it encourages
  cross-area constraints and compatible migration schedules.
- Start with two PostgreSQL databases — not selected because named schemas give
  sufficient isolation during experimentation with less local operational
  overhead.
- Preserve and translate existing rows — not selected because current development
  data is disposable and the old mapping would constrain the new boundaries.

## Behavioral examples

- A fact extracted from a general Chat conversation may be reused by another Chat
  conversation but is never visible in a Characters continuity.
- A Characters identity or persona can be deleted, duplicated, or evolved without
  changing any Chat conversation or memory.
- Characters migrations can run without importing Chat metadata, and its schema
  can later be moved to another database without rewriting Chat records.
