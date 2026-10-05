# Chat Buddy

Chat Buddy is a local-first conversational AI application with two independent
experiences:

- **Chat** for general-purpose conversations with durable context and
  user-managed memory.
- **Characters** for persistent persona-based conversations and relationship
  continuity.

![Python Version from PEP 621 TOML](https://img.shields.io/python/required-version-toml?tomlFilePath=https://github.com/babaksoft/chat-buddy/raw/refs/heads/master/pyproject.toml)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/babaksoft/chat-buddy/ci.yml)
![GitHub License](https://img.shields.io/github/license/babaksoft/chat-buddy)

## What you can do

### Chat

- Create, rename, resume, and delete persistent conversations.
- Stream responses from models available through Ollama.
- Optionally use OpenAI for visible responses.
- Keep long conversations coherent with rolling summaries.
- Reuse extracted memories across Chat conversations.
- Inspect, correct, exclude, reactivate, or permanently delete memories.
- Recover safely from interrupted generation attempts.

### Characters

- Create identities and manage their complete authored details on a dedicated
  page.
- Edit identities until first use, then duplicate a frozen identity with revised
  details when changes are needed.
- Create and manage personas.
- Start isolated Ongoing continuities with an explicit relationship setup.
- Resume active or archived conversation history.
- Stream persona responses through a Characters-owned Ollama configuration.
- Compress long conversations with continuity-scoped rolling summaries.
- Recover incomplete turns without committing partial output.
- Duplicate frozen profiles when authored changes are needed.

## Product model and scope

| Area | Purpose | Context and memory | Persistence |
|---|---|---|---|
| Chat | General conversations | Conversation summaries and user-controlled Chat-wide memory | PostgreSQL `chat` schema |
| Characters | Persona-based continuities | Continuity-local transcript and rolling summary | PostgreSQL `characters` schema |

Chat and Characters are independent product areas. They do not share
conversations, memories, repositories, prompts, or database records. Streamlit
provides only the common navigation shell.

Characters currently supports Ongoing conversations. Each continuity belongs to
one identity and persona, starts with an explicit relationship state, and remains
isolated from other continuities. Characters does not currently extract long-term
memory or evolve relationship and persona state from conversation content.

## Local-first behavior and cloud usage

PostgreSQL stores application data in the configured local database. Ollama
provides the default generation path for both areas and also performs Chat title
generation, rolling summarization, and memory extraction.

OpenAI is an explicit, optional provider for visible Chat responses. When selected,
the eligible current input, recent turns, conversation summary, and active Chat
memories are sent to OpenAI. Persistence and Chat utility operations remain on the
configured Ollama endpoint. Requests may be billable, provider retention policies
may apply, and deleting local data cannot retract content already sent to an
external provider.

Chat and Characters use separate provider configuration. Data sent to an Ollama
endpoint remains under the control of that endpoint and the selected model; verify
their hosting behavior when local-only processing is required.

## Architecture at a glance

```text
                         Streamlit shell
                         /              \
                  Chat area          Characters area
                 /         \          /           \
        Application       Domain   Application    Domain
            |                           |
       Infrastructure              Infrastructure
        /          \                /           \
   LLM providers  chat schema   LLM providers  characters schema
```

Each area owns its domain models, application services, prompts, repositories,
provider contracts, and persistence. Dependencies point inward. The shared package
contains only generic configuration, logging, and low-level technical utilities.
See [DESIGN.md](DESIGN.md) for the full product and architecture design.

## Technology stack

| Responsibility | Technology |
|---|---|
| Language and environment | Python 3.12, uv |
| User interface | Streamlit |
| Domain values and validation | Pydantic |
| Persistence | PostgreSQL, SQLAlchemy |
| Migrations | Alembic |
| Local model access | Ollama |
| Optional cloud responses | OpenAI |
| Testing and quality | pytest, mypy, Ruff, Black, isort |

## Quick start

### Prerequisites

Install the following before starting:

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker with Compose
- [Ollama](https://ollama.com/)
- Git

An OpenAI account and API key are optional.

### 1. Clone and install

```bash
git clone https://github.com/babaksoft/chat-buddy.git
cd chat-buddy
uv sync --locked
```

### 2. Start PostgreSQL

```bash
docker-compose up -d
```

The Compose service creates the `chat_buddy` database expected by the checked-in
configuration.

### 3. Apply migrations

```bash
uv run alembic -c alembic-chat.ini upgrade head
uv run alembic -c alembic-characters.ini upgrade head
```

The two commands maintain independent histories for the `chat` and `characters`
schemas.

### 4. Prepare Ollama

Start Ollama and make the configured models available:

```bash
ollama serve
```

The checked-in Chat configuration uses `gpt-oss:20b-cloud` for responses and
utility operations. Characters defaults to `mistral` for responses and summaries.
Prepare those models according to their Ollama requirements, or change the
configuration described below to models available on your endpoint.

### 5. Start Chat Buddy

```bash
uv run streamlit run src/chat_buddy/ui/streamlit_app.py
```

Open the URL printed by Streamlit, normally `http://localhost:8501`. Chat is the
default page; use the sidebar to switch to Characters.

### 6. Try the application

#### Try Chat

1. Open **Chat**.
2. Create a conversation.
3. Select a provider and model.
4. Send several messages.
5. Open **Memory** to inspect or manage extracted memories.

#### Try Characters

1. Open **Identities** to create, inspect, or edit who you are in Characters.
2. Open **Characters** and select an identity.
3. Create a persona.
4. Review and confirm an Ongoing start.
5. Send a message and resume the continuity from the sidebar.

Confirming the first continuity permanently freezes the selected identity and
persona. Duplicate a frozen profile to create an editable variant. Archived
continuities remain readable but cannot accept new messages.

## Configuration

When Streamlit starts, Chat Buddy loads optional settings from `.env` in the
repository root. Copy `.env.example` to `.env` and add local values there when you
do not want to export them in every terminal. The file is ignored by Git, and
variables already set in the launching shell take precedence.

### Chat

Chat settings currently live in
`src/chat_buddy/chat/infrastructure/config/settings.py`.

| Setting | Checked-in value | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://postgres:postgres@localhost:5432/chat_buddy` | Chat database connection |
| `OLLAMA_ENDPOINT_URL` | `http://172.31.80.1:11434` | Ollama endpoint used by Chat |
| `CHAT_MODEL` | `gpt-oss:20b-cloud` | Default visible-response model |
| `UTILITY_MODEL` | `gpt-oss:20b-cloud` | Title, summary, and memory model |

These values are source-configured rather than environment-backed. Adjust them for
your local Ollama installation before launching the application. Keep the declared
context and output limits compatible with the selected model.

### Characters

Characters reads its model settings when its services are composed:

| Environment variable | Default | Purpose |
|---|---|---|
| `CHARACTERS_OLLAMA_ENDPOINT_URL` | `http://localhost:11434` | Characters Ollama endpoint |
| `CHARACTERS_RESPONSE_MODEL` | `gpt-oss:20b-cloud` | Persona response model |
| `CHARACTERS_SUMMARY_MODEL` | `gpt-oss:20b-cloud` | Rolling-summary model |
| `CHARACTERS_CONTEXT_TOKENS` | `8192` | Total configured context window |
| `CHARACTERS_OUTPUT_TOKENS` | `1024` | Default output-token limit |

For example:

```bash
export CHARACTERS_OLLAMA_ENDPOINT_URL=http://localhost:11434
export CHARACTERS_RESPONSE_MODEL=gpt-oss:20b-cloud
export CHARACTERS_SUMMARY_MODEL=gpt-oss:20b-cloud
export CHARACTERS_CONTEXT_TOKENS=8192
export CHARACTERS_OUTPUT_TOKENS=1024
```

The Characters database URL is currently source-configured in
`src/chat_buddy/characters/infrastructure/config/settings.py` and defaults to the
same local PostgreSQL database as Chat.

### Optional OpenAI responses

OpenAI is disabled by default and applies only to visible Chat responses. Enable it
with a Chat-specific API key:

```bash
export CHAT_OPENAI_ENABLED=true
export CHAT_OPENAI_API_KEY="your-api-key"
uv run streamlit run src/chat_buddy/ui/streamlit_app.py
```

Chat deliberately does not read `OPENAI_API_KEY`. Ollama must still be reachable
for titles, summaries, and memory extraction. Review the usage notice in the UI
before selecting an OpenAI model.

## Database management

Always use the migration configuration owned by the area being changed:

```bash
uv run alembic -c alembic-chat.ini current
uv run alembic -c alembic-characters.ini current
```

Chat migrations update `chat.alembic_version`; Characters migrations update
`characters.alembic_version`. There is intentionally no root `alembic.ini`. The
root `alembic/versions/` history is abandoned and retained only as a reference; do
not run or extend it.

### Reset a disposable local database

> **Warning:** This permanently deletes the local Compose database volume and all
> application data stored in it.

```bash
docker-compose down --volumes
docker-compose up -d
uv run alembic -c alembic-chat.ini upgrade head
uv run alembic -c alembic-characters.ini upgrade head
```

## Development

Run the complete local quality suite:

```bash
scripts/check.sh
```

This checks formatting, import ordering, linting, type safety, and the automated
test suite. Ordinary tests use fake or mocked providers and do not require live
model calls.

Some PostgreSQL concurrency cases and provider smoke tests are explicitly enabled:

```bash
CHARACTERS_TEST_DATABASE_URL=postgresql+psycopg2://postgres:test@localhost:55432/characters_test \
  scripts/check.sh

CHAT_OPENAI_SMOKE_TEST=true uv run pytest -v -m openai_smoke
CHARACTERS_OLLAMA_SMOKE_TEST=true uv run pytest -v -m characters_ollama_smoke
```

Use a disposable PostgreSQL test database whose name ends in `_test`. OpenAI smoke
tests are networked and billable; Ollama smoke tests require the configured local
service and model.

## Project documentation

- [README.md](README.md) — stable product overview, setup, configuration, and basic
  operation.
- [DESIGN.md](DESIGN.md) — product model, architecture, invariants, and intended
  behavior.
- [PLAN.md](PLAN.md) — implementation sequence, delivery status, and future work.
- [Decision records](docs/decisions/) — concise accepted decisions and their
  rationale.
- [AGENTS.md](AGENTS.md) — repository conventions for coding and documentation
  work.

## License

Chat Buddy is available under the [MIT License](LICENSE).
