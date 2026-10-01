# Chat Buddy

A conversational AI application for interacting with local LLMs through a persistent chat interface.

![Python Version from PEP 621 TOML](https://img.shields.io/python/required-version-toml?tomlFilePath=https://github.com/babaksoft/chat-buddy/raw/refs/heads/master/pyproject.toml)
![Static Badge](https://img.shields.io/badge/category-GenAI-orange)
![Static Badge](https://img.shields.io/badge/framework-LlamaIndex-orange)
![GitHub License](https://img.shields.io/github/license/babaksoft/chat-buddy)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/babaksoft/chat-buddy/ci.yml)


## Goals

- Persistent conversations
- Conversation resume support
- Context window management
- Local-first deployment
- Observability and monitoring

## Technology Stack

- Python 3.12
- Streamlit
- Ollama
- PostgreSQL
- SQLAlchemy
- Alembic
- LlamaIndex
- Arize Phoenix
- Prometheus
- Grafana

## Architecture

```text
UI (Streamlit)
    ↓
Application Services
    ↓
LLM Gateway + Repository
    ↓          ↓
Ollama + PostgreSQL
```

## Development Status

- [x] Logging
- [x] Database Connectivity
- [x] ORM Models
- [x] Alembic Migrations
- [x] Repository Layer
- [x] Application Services
- [x] Ollama Integration
- [x] Streamlit Chat UI
- [x] Context Management
- [x] Memory Retrieval
- [ ] Evaluation Framework
- [ ] Monitoring Dashboard

## Application Areas

Use the sidebar to switch between two areas:

- **Chat** opens by default and provides the existing conversation history,
  streaming replies, renaming, and deletion. Switching areas preserves the selected
  conversation for the current browser session.
- **Characters** retains a landing page while identity management is available
  through its backend service. Persona cores can also be managed through backend
  services; character chat is not implemented yet. The landing page does not
  connect to PostgreSQL or Ollama.

Start the application with the existing command:

```bash
uv run streamlit run src/chat_buddy/ui/streamlit_app.py
```

The Characters landing page is also available at `/characters`.

## Ollama requirements

Ollama is required even when OpenAI supplies the visible response. Chat uses the
configured local utility model for conversation titles, rolling summaries, and
completed-turn memory extraction. Before starting Chat, make sure Ollama is
reachable at `OLLAMA_ENDPOINT_URL` and that both `CHAT_MODEL` and
`UTILITY_MODEL` from
`src/chat_buddy/chat/infrastructure/config/settings.py` are available. If the
utility model is unavailable, visible cloud responses may still succeed, but
title, summary, or memory processing can fail independently and will be retried
only according to their documented application policy.

## Optional OpenAI responses

Chat remains Ollama-only by default. To opt into the response-only OpenAI
provider, set both variables before starting Streamlit:

```bash
export CHAT_OPENAI_ENABLED=true
export CHAT_OPENAI_API_KEY="your-api-key"
uv run streamlit run src/chat_buddy/ui/streamlit_app.py
```

OpenAI is omitted when it is disabled or its Chat-specific key is blank; Chat
does not read `OPENAI_API_KEY`. The curated OpenAI models are used only for
visible Chat responses. Titles, rolling summaries, and memory extraction remain
on Ollama. Requests are billable and send the assembled current input, recent
turns, conversation summary, and eligible Chat-wide memories to OpenAI with
response storage disabled. Provider abuse-monitoring retention may still apply.
Local deletion cannot retract data already transmitted to the provider.

## Chat memory controls and data flow

Memory extraction runs only after a complete user/assistant turn. Active Chat
memories are reusable across Chat conversations, while rolling summaries and
ordinary messages remain scoped to their source conversation. Neither form of
Chat context is shared with Characters.

Open **🧠 Memory** from the Chat sidebar to inspect stored content and its source
provenance. You can correct an active memory, exclude it from future prompts,
reactivate an excluded memory, or permanently delete the complete memory lineage
and provenance. Deleting a source conversation leaves reusable Chat memory in
place but marks its source unavailable; delete the memory separately when it
must also be purged.

With Ollama selected, assembled prompt data and responses remain on the
configured Ollama endpoint. With OpenAI selected, the eligible current input,
recent turns, active conversation summary, and admitted active memories are sent
to OpenAI for the visible response. Persistence, title generation, rolling
summarization, and memory extraction remain local. Review the OpenAI usage notice
before enabling it, because local correction or deletion cannot retract content
already sent to a cloud provider.

The optional live smoke test is networked and billable. It is skipped unless
`CHAT_OPENAI_SMOKE_TEST=true` and `CHAT_OPENAI_API_KEY` is non-blank:

```bash
CHAT_OPENAI_SMOKE_TEST=true uv run pytest -v -m openai_smoke
```

## Database setup

Chat persistence has an independent migration history in the PostgreSQL
`chat` schema, and Characters has its own identity migration history in the
`characters` schema. Stage 1 did not migrate data from the legacy public-schema
tables, and Stage 3 does not convert the provisional key/value memory shape.
Existing pre-split development databases must therefore be recreated before
applying the area baselines. The reset below deletes all data in the local
Compose database volume:

```bash
docker-compose down --volumes
docker-compose up -d
uv run alembic -c alembic-chat.ini upgrade head
uv run alembic -c alembic-characters.ini upgrade head
```

Run future revisions, upgrades, downgrades, and history inspection with the
owning area's configuration: `alembic-chat.ini` for Chat and
`alembic-characters.ini` for Characters. Chat migrations update
`chat.alembic_version`; Characters migrations update
`characters.alembic_version`. There is intentionally no default `alembic.ini`,
so bare Alembic commands fail instead of targeting the wrong migration history.
The unchanged files in `alembic/versions/` are retained only as a legacy
reference.

## Running tests

```bash
scripts/check.sh
```


### Characters identity backend

Apply the new Characters revision to an existing Stage 1–3 database with
`uv run alembic -c alembic-characters.ini upgrade head`. It creates
`characters.identities` and leaves Chat and legacy tables unchanged. No database
reset is needed for this slice. No new runtime settings or Ollama setup is needed.
The Characters UI remains a landing page until the later UI slice.

Compose `IdentityService` from
`chat_buddy.characters.application.identity_service` with
`DbIdentityRepository` from
`chat_buddy.characters.infrastructure.db.repositories.identity_repository` and
`CharactersSessionLocal` from the Characters database package. The service exposes
`create`, `list`, `inspect`, `edit`, `duplicate`, and `ensure_default` operations.
Supply `IdentityDetails` values for authored fields and the last observed revision
for edits. Default setup is explicit and idempotent; merely importing the service
or using Chat does not create **You**. Frozen records can be duplicated but cannot
be edited. Starting a continuity now permanently freezes both reviewed profiles.

### Characters persona backend

Apply revision `5cb588ac2285` with
`uv run alembic -c alembic-characters.ini upgrade head`. It adds only
`characters.personas` after the identity revision; no reset, new settings, or
provider setup is needed. The UI remains the landing page.

Compose `PersonaService` from
`chat_buddy.characters.application.persona_service` with `DbPersonaRepository`
from `chat_buddy.characters.infrastructure.db.repositories.persona_repository`
and the Characters session factory. It exposes `create`, `list`, `inspect`,
`edit`, and `duplicate`. Supply a `PersonaCore` with a required `name` and
`definition`, plus optional free-form `traits`. Limits are 128, 8192, and 4096
characters respectively; supplied fields are trimmed and must be nonblank.
Edits replace the entire core at the expected revision. Duplicates may supply a
revised core and always start editable at revision 1 under a new UUID. Both
service and repository reject frozen or stale edits. Starting a continuity
permanently freezes the persona globally, including its display name; there is no
unfreeze operation.

### Characters Ongoing lifecycle backend

Apply revision `83a2c09d7f41` with
`uv run alembic -c alembic-characters.ini upgrade head`. It adds Characters-only
continuities, sole conversations, and starting relationship snapshots, including
the active Ongoing uniqueness constraint. No reset or new configuration is needed;
Chat and legacy migration histories are unchanged. The UI remains a landing page.

Compose `ContinuityService` from
`chat_buddy.characters.application.continuity_service` with
`DbContinuityRepository` from
`chat_buddy.characters.infrastructure.db.repositories.continuity_repository`
and the Characters session factory. `start` accepts a frozen `StartContinuity`
value containing a confirmation UUID, both profile identifiers and reviewed
revisions, and a `RelationshipSelection`. It transactionally freezes both profiles
and creates all continuity records. Repeated identical confirmations return the
original continuity; changed confirmations need a new UUID. Stale reviewed
profiles require renewed review. Only Ongoing can be created.

`resume` and `archive` require identity, persona, and continuity identifiers.
`list_grouped` returns identity/persona groups including archived history.
Archiving is permanent and read-only, keeps both profiles frozen, and releases the
pair's active slot. A replacement needs explicit confirmation and an independent
starting relationship. The vocabulary and compatibility table are in
[DESIGN.md](DESIGN.md#ongoing-starting-relationship). No inferred evolution,
messages, providers, or extracted memory are introduced by this slice.

Portable Characters tests run without PostgreSQL or providers:

```bash
uv run pytest tests/characters tests/integration/characters -m 'not characters_postgres'
```

PostgreSQL acceptance uses an explicit test URL. Its database name must end in
`_test`; the role must be able to create databases. Each test creates a unique
scratch database, then drops it. To run the database validation locally:

```bash
docker run --detach --rm --name chat-buddy-characters-test \
  -e POSTGRES_PASSWORD=test -e POSTGRES_DB=characters_test \
  -p 127.0.0.1:55432:5432 postgres:17
# Wait until PostgreSQL is ready, then run all checks with database cases enabled.
CHARACTERS_TEST_DATABASE_URL=postgresql+psycopg2://postgres:test@127.0.0.1:55432/characters_test \
  scripts/check.sh
docker stop chat-buddy-characters-test
```

Without this setting, PostgreSQL cases are skipped by ordinary tests. A slice's
local database validation must run them explicitly before marking it verified.
They exercise concurrent default setup, competing identity/persona edits, first-use
races, shared-persona starts, confirmation collisions, active-only uniqueness,
fresh upgrades, baseline and prior-head downgrade/re-upgrade, metadata parity, and
preservation of a populated Chat schema including its migration version. Offline
migration checks run in the ordinary suite.
