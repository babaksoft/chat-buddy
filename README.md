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
- Create, inspect, edit, and duplicate personas on a dedicated page.
- Define and preview an explicit relationship before confirming a new isolated
  Ongoing continuity.
- Navigate every active or archived continuity by its identity and persona, and
  resume its conversation history.
- Stream persona responses through a Characters-owned Ollama configuration.
- Compress long conversations with continuity-scoped rolling summaries.
- Recover incomplete turns without committing partial output.
- Retry a completed persona response up to three times and select any saved
  alternative.
- Branch an Ongoing conversation from an earlier persona response without losing
  either future.
- Create a named Storyline with an initial scene, then append scenes one at a time
  as the narrative advances.
- Converse, retry responses, select alternatives, and branch within the latest
  Storyline scene while preserving saved futures.
- Fork an older Storyline scene into an independently owned Storyline under an
  exact duplicate of either source profile.
- Use branch-aware, time-aware Storyline memory extracted after complete turns.
- Inspect memory evidence and revisions; correct, exclude, reactivate, or
  permanently delete memories; and review extraction conflicts.
- Archive a Storyline as read-only and start a fresh independent Storyline for the
  same identity and persona.
- Duplicate frozen profiles when authored changes are needed.

## Product model and scope

| Area | Purpose | Context and memory | Persistence |
|---|---|---|---|
| Chat | General conversations | Conversation summaries and user-controlled Chat-wide memory | PostgreSQL `chat` schema |
| Characters | Persona-based Ongoing and Storyline continuities | Ongoing rolling summaries; scene-local Storyline summaries and continuity-scoped Storyline memory | PostgreSQL `characters` schema |

Chat and Characters are independent product areas. They do not share
conversations, memories, repositories, prompts, or database records. Streamlit
provides only the common navigation shell.

Characters supports Ongoing and Storyline conversations. Each continuity belongs
to one identity and persona, starts with an explicit relationship state, and
remains isolated from other continuities. Ongoing uses a rolling summary and does
not extract long-term memory. A Storyline owns ordered scenes and its own extracted
memory; branch and scene-time rules prevent unrelated or future knowledge from
entering a prompt. Storyline memory crosses into another continuity only through a
reviewed Storyline fork, which creates an independent lineage by remapping copied
evidence. Characters does not yet evolve relationship or persona state from
conversation content.

## Local-first behavior and cloud usage

PostgreSQL stores application data in the configured local database. Ollama
provides the default generation path for both areas. It also performs Chat title
generation, summarization, and memory extraction, plus Characters summarization
and Storyline memory extraction.

OpenAI is an explicit, optional provider for visible Chat responses. When selected,
the eligible current input, recent turns, conversation summary, and active Chat
memories are sent to OpenAI. Persistence and Chat utility operations remain on the
configured Ollama endpoint. Requests may be billable, provider retention policies
may apply, and deleting local data cannot retract content already sent to an
external provider.

Chat and Characters use separate provider configuration. Depending on the
Characters operation, its Ollama endpoint may receive the authored identity and
persona, starting relationship, eligible Storyline memory, scene setup, compatible
summary, selected-path messages, and the current or newly completed turn. Data sent
to an Ollama endpoint remains under the control of that endpoint and selected
model. If either points to a hosted or remote service, that eligible context leaves
the local machine; verify the endpoint and model hosting behavior when local-only
processing is required.

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

The checked-in Chat configuration and the Characters defaults use
`gpt-oss:20b-cloud` for responses and utility operations.
Prepare those models according to their Ollama requirements, or change the
configuration described below to models available on your endpoint.

### 5. Start Chat Buddy

```bash
uv run streamlit run src/chat_buddy/ui/streamlit_app.py
```

Open the URL printed by Streamlit, normally `http://localhost:8501`. Chat is the
default page; use the sidebar to open the focused Characters pages.

### 6. Try the application

#### Try Chat

1. Open **Chat**.
2. Create a conversation.
3. Select a provider and model.
4. Send several messages.
5. Open **Memory** to inspect or manage extracted memories.

#### Try Characters

1. Open **Identities** to create, inspect, or edit who you are in Characters.
2. Open **Personas** to create, inspect, or edit who you want to talk with.
3. For a continuous conversation, open **New Ongoing**, define and review the
   starting relationship, then confirm it. Use **Ongoing** to chat, retry a
   response, select an alternative, or branch without deleting a saved future.
4. For a scene-based narrative, open **New Storyline**, select the profiles, name
   the Storyline, define its starting relationship and first scene, then review and
   confirm it.
5. Use **Storylines** to chat in the latest scene. After that scene has a complete
   exchange, append the next scene. Older scenes remain readable; branching from
   one with later scenes opens a reviewed fork that exactly duplicates either the
   identity or persona and leaves the source unchanged.
6. On the selected Storyline, inspect its memory and conflicts below the scene.
   Corrections, exclusions, reactivations, and confirmed permanent deletions affect
   that Storyline only. Archived Storylines and their memory are read-only.
7. Navigate active or archived histories under their identity and persona.

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
| `CHARACTERS_MEMORY_EXTRACTION_MODEL` | `gpt-oss:20b-cloud` | Storyline memory-extraction model |
| `CHARACTERS_CONTEXT_TOKENS` | `32768` | Total configured context window |
| `CHARACTERS_OUTPUT_TOKENS` | `4096` | Default output-token limit |

For example:

```bash
export CHARACTERS_OLLAMA_ENDPOINT_URL=http://localhost:11434
export CHARACTERS_RESPONSE_MODEL=gpt-oss:20b-cloud
export CHARACTERS_SUMMARY_MODEL=gpt-oss:20b-cloud
export CHARACTERS_MEMORY_EXTRACTION_MODEL=gpt-oss:20b-cloud
export CHARACTERS_CONTEXT_TOKENS=8192
export CHARACTERS_OUTPUT_TOKENS=1024
```

The response, summary, and memory-extraction models are independently selectable
but must all be available through the configured Characters Ollama endpoint.
Storyline extraction uses the context and output limits above with its own bounded
input selection; it does not make Ongoing memory-bearing.

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
