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
- **Characters** provides inline identity and persona management, reviewed Ongoing
  starts, and active/archived navigation. Setup uses its independent PostgreSQL
  schema and needs no running Ollama. Conversation UI arrives in Slice 9.

Start the application with the existing command:

```bash
uv run streamlit run src/chat_buddy/ui/streamlit_app.py
```

The Characters page is also available at `/characters`.

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
The Characters page now offers profile setup and confirmed Ongoing starts.

Compose `IdentityService` from
`chat_buddy.characters.application` with
`DbIdentityRepository` from
`chat_buddy.characters.infrastructure.db.repositories` and
`CharactersSessionLocal` from the Characters database package. The service exposes
`create`, `list`, `inspect`, `edit`, `duplicate`, and `ensure_default` operations.
Supply `IdentityDetails` values for authored fields and the last observed revision
for edits. Default setup is explicit and idempotent; merely importing the service
or using Chat does not create **You**. Frozen records can be duplicated but cannot
be edited. Starting a continuity now permanently freezes both reviewed profiles.

### Characters profile and Ongoing setup

Open **Characters** to initialize the default **You** identity. Select an identity
and persona in the sidebar, create or edit authored profiles inline, and use
**Review start** followed by **Confirm start** to create Ongoing. Confirmation
permanently freezes both profiles; use **Duplicate identity** or **Duplicate
persona** for later authored changes. Review and cancellation leave profiles
editable. Changed profile revisions require a new review.

Each Ongoing starts with a fresh relationship and an isolated conversation and
rolling summary, without extracted memory or inherited shared events. Established
relationships require explicit social and romantic statuses. Active and archived
continuities appear under the selected identity/persona pair. Select one to resume
its lifecycle view; **Archive Ongoing** makes it read-only without creating a
replacement. Conversation rendering and sending arrive in Slice 9.

This UI uses the existing Characters migrations and database configuration; it
adds no migration or runtime setting and needs no running provider for setup.
Only the Characters route constructs its profile services. Chat selection and
Characters selection survive switching areas independently.

### Characters persona backend

Apply revision `5cb588ac2285` with
`uv run alembic -c alembic-characters.ini upgrade head`. It adds only
`characters.personas` after the identity revision; no reset, new settings, or
provider setup is needed. The Characters UI supports inline persona management.

Compose `PersonaService` from
`chat_buddy.characters.application` with `DbPersonaRepository`
from `chat_buddy.characters.infrastructure.db.repositories`
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
Chat and legacy migration histories are unchanged.

Compose `ContinuityService` from
`chat_buddy.characters.application` with
`DbContinuityRepository` from
`chat_buddy.characters.infrastructure.db.repositories`
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

### Characters provider backend

Slice 4 adds Characters-owned streaming response and summary capabilities without
schema changes. No running Ollama service is needed for ordinary tests.

Call `create_model_registry()` from
`chat_buddy.characters.infrastructure.llm` only when composing
Characters services. `resolve_default("response")` and `resolve_default("summary")`
return independent effective selections. `resolve` also accepts an explicit
configured provider/model pair and generation overrides. Select the matching
`response_gateway`, `summary_gateway`, and `token_counter` using the effective
model's provider key. Response adapters yield text through `stream`; callers must
close the iterator when abandoning output. Summary adapters accept an assembled
prompt and return nonempty plain text.

Environment settings are read when the factory is called:

| Setting | Default | Purpose |
|---|---|---|
| `CHARACTERS_OLLAMA_ENDPOINT_URL` | `http://localhost:11434` | Local Ollama endpoint |
| `CHARACTERS_RESPONSE_MODEL` | `mistral` | Default persona response model |
| `CHARACTERS_SUMMARY_MODEL` | `mistral` | Default summary model |
| `CHARACTERS_CONTEXT_TOKENS` | `8192` | Configured total model context window |
| `CHARACTERS_OUTPUT_TOKENS` | `1024` | Default enforced output token limit |

Pull both selected models with `ollama pull <model>` before local invocation.
Set context limits to values supported by the selected models. The local counter
uses a conservative UTF-8 byte estimate with framing overhead, not exact usage.
These settings and clients are independent of Chat configuration.

### Characters durable Ongoing backend

Slice 5 adds migration `f71d92ab0c55`: conversation generation defaults,
append-only messages, and a separate generation ledger. Apply it with
`uv run alembic -c alembic-characters.ini upgrade head`; Chat migrations and
configuration are independent. Existing continuities remain usable. No additional
provider settings are required. Conversation UI arrives in Slice 9.

Compose the backend lazily with `create_conversation_service()` from
`chat_buddy.characters.infrastructure`. Every operation
requires a `ConversationScope` containing identity, persona, continuity, and
conversation identifiers. `send(scope, SubmittedInput(content=...))` commits the
input and returns a pending attempt. Exhaust `stream(scope, attempt.id)` to commit
the persona response; use `contextlib.closing` when consumption may stop early.
`history` returns saved messages and attempts separately. `configure` validates
and saves a `ConversationSettings` selection for the next attempt without changing
past effective settings.

`resume` reloads history and interrupts attempts whose progress heartbeat is at
least five minutes old. Closing a consumed stream interrupts it immediately.
`continue_incomplete_turn` reserves a fresh attempt for the existing unmatched
user input, preserving previous failures and partial output. Another send must
wait for that input to complete. Archived history remains readable and cannot
accept generation writes. Completion checks archival again after the provider
returns.

The prompt includes required persona, identity, starting relationship, fixed
presentation, and all committed history. Partial output stays outside it. Token
accounting reserves output capacity and 64 additional overhead tokens; overflow
raises `ContextCapacityError` before saving an attempt or calling a provider.
Rolling summaries arrive in Slice 6. Ongoing performs no memory extraction or
relationship/persona evolution.
