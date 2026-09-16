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
streamlit run src/chat_buddy/ui/streamlit_app.py
```

The Characters landing page is also available at `/characters`.

## Database setup

Chat persistence now has an independent migration history in the PostgreSQL
`chat` schema, and Characters has its own empty migration history in the
`characters` schema. Stage 1 does not migrate data from the legacy public-schema
tables, so existing development databases must be recreated before applying
the area baselines. The reset below deletes all data in the local Compose
database volume:

```bash
docker-compose down --volumes
docker-compose up -d
uv run alembic -c alembic-chat.ini upgrade head
uv run alembic -c alembic-characters.ini upgrade head
```

Run future revisions and upgrades with the owning area's configuration:
`alembic-chat.ini` for Chat and `alembic-characters.ini` for Characters. The
default `alembic.ini` and files in `alembic/versions/` remain the unchanged
legacy history during the Stage 1 transition.

## Running Tests

pytest
