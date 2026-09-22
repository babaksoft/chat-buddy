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
- **Characters** is a landing-page scaffold for future character profiles and
  conversations. Persona creation and character chat are not implemented yet.
  This area does not connect to PostgreSQL or Ollama.

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
`chat` schema, and Characters has its own empty migration history in the
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
