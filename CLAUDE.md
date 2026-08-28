# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Chat Buddy is a conversational AI application that provides a ChatGPT-like experience using local LLMs (via Ollama) with persistent conversations, context management, and memory capabilities.

**Tech Stack**: Python 3.12, Streamlit, Ollama, PostgreSQL, SQLAlchemy, Alembic, LlamaIndex, Arize Phoenix

## Architecture

The codebase follows **Clean Architecture** with clear separation of concerns:

```
src/chat_buddy/
├── domain/              # Core business logic (Protocol interfaces, domain models)
│   ├── llm_gateway.py   # LLM abstraction (Protocol)
│   ├── chat.py          # Chat domain models
│   ├── summarizer.py    # Summarization interface
│   ├── context_builder.py
│   └── tokenizer.py
├── application/         # Application services and use cases
│   ├── service/
│   │   ├── chat_service.py
│   │   ├── conversation_service.py
│   │   └── memory_service.py
│   ├── context_builder.py
│   ├── llm_summarizer.py
│   └── schemas.py
├── infrastructure/      # External integrations
│   ├── db/             # Database (SQLAlchemy models, repositories)
│   │   ├── models/
│   │   └── repositories/
│   ├── llm/            # Ollama integration
│   ├── tokenization/   # Token counting
│   └── config/         # Settings, logging
├── prompts/            # LLM prompt templates (keep all prompts here)
└── ui/                 # Streamlit interface
    └── streamlit_app.py
```

**Key Architectural Patterns:**
- **Dependency Inversion**: Domain layer defines `Protocol` interfaces (e.g., `LLMGateway`, `Summarizer`), infrastructure implements them
- **Repository Pattern**: All database access goes through repository classes
- **Service Layer**: Business logic encapsulated in application services
- **Dependency Injection**: Services are wired up in `streamlit_app.py`'s `build_services()` function

## Development Setup

### Prerequisites
1. **Python 3.12+** (required)
2. **PostgreSQL** running on `localhost:5432`
   - Quick start: `docker-compose up -d` (uses `docker-compose.yml`)
   - Database: `chat_buddy`, user: `postgres`, password: `postgres`
3. **Ollama** running on `http://localhost:11434`
   - Default models: `samantha-mistral:7b` (chat), `llama3.2:3b` (utility tasks like title generation)

### Installation
```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install project
pip install -c constraints.txt -e .

# Install dev dependencies
pip install -c constraints.txt -e ".[dev]"
```

### Database Migrations
```bash
# Apply all migrations
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"

# Check current migration status
alembic current

# Rollback one migration
alembic downgrade -1
```

## Running the Application

### Start the Streamlit UI
```bash
streamlit run src/chat_buddy/ui/streamlit_app.py
```
The app will open in your browser at `http://localhost:8501`

## Development Commands

### Code Quality
```bash
# Format code (must pass before committing)
black .
isort .

# Check formatting without changes
black --check .
isort --check-only .

# Lint
ruff check .

# Type checking
mypy .
```

### Testing
```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/application/test_chat_service.py

# Run tests with coverage
pytest --cov=chat_buddy
```

**Test Structure:**
- `tests/application/` - Application service tests
- `tests/infrastructure/` - Infrastructure layer tests (DB, LLM integration)
- `tests/integration/` - End-to-end integration tests
- `conftest.py` - Shared test fixtures

## Configuration

**Settings Location**: `src/chat_buddy/infrastructure/config/settings.py`

Key configuration:
- `DATABASE_URL` - PostgreSQL connection string
- `OLLAMA_ENDPOINT_URL` - Ollama server URL
- `CHAT_MODEL` - Primary chat model (default: `samantha-mistral:7b`)
- `UTILITY_MODEL` - Utility model for summaries/titles (default: `llama3.2:3b`)
- `MODEL_CONTEXT_WINDOW` - Token limit (default: 32,768)
- `SUMMARY_TRIGGER_RATIO` - When to trigger summarization (default: 0.85)
- `MEMORY_EXTRACTION_INTERVAL` - Extract memories every N messages (default: 10)

Environment variables can be set in `.env` file (already present in repo)

## Key Domain Concepts

### Chat Flow
1. User sends message → `ChatService.chat()`
2. Context built from conversation history + retrieved memories → `ContextBuilder`
3. LLM generates response via `OllamaGateway` (implements `LLMGateway` protocol)
4. Response saved to database via `ConversationRepository`
5. Periodically, memories extracted via `MemoryService`

### Context Management
- Token counting tracks context window usage (`MistralTokenCounter`)
- When context exceeds `SUMMARY_TRIGGER_RATIO`, older messages are summarized
- Summary stored as a "system" role message in the conversation

### Memory System
- Long-term facts extracted from conversations using LLM
- Stored in `memories` table with timestamps
- Injected into context before conversation context is built

## Working with Prompts

**All LLM prompts must be defined in `src/chat_buddy/prompts/`**
- `chat_templates.py` - System prompts for chat
- `memory.py` - Memory extraction prompts
- `summary.py` - Summarization prompts
- `title.py` - Conversation title generation

## Code Conventions

- **Type hints required** on all function signatures
- **Google-style docstrings** required when they add value
- **Protocol interfaces** in domain layer for abstractions
- **Repository pattern** for all database access (no direct SQLAlchemy queries outside repositories)
- **Service layer** contains business logic, never put business logic in repositories or UI
- Use `dataclasses` with `slots=True, frozen=True` for immutable domain models
- Automated tests required for new features

## CI/CD

GitHub Actions workflow (`.github/workflows/ci.yml`) runs on push to `master`:
- Code formatting checks (black, isort)
- Linting (ruff)
- Type checking (mypy)
- Unit tests (pytest)

All checks must pass before merging.

## Common Development Tasks

### Adding a New LLM Operation
1. Define interface in `domain/llm_gateway.py` (add method to `LLMGateway` Protocol)
2. Implement in `infrastructure/llm/ollama_gateway.py`
3. Add prompt template in `prompts/`
4. Use in application service

### Adding a New Database Model
1. Create model in `infrastructure/db/models/`
2. Create repository in `infrastructure/db/repositories/`
3. Generate migration: `alembic revision --autogenerate -m "add_table"`
4. Review and apply: `alembic upgrade head`

### Modifying Conversation Flow
- Start at `ChatService.chat()` in `application/service/chat_service.py`
- Context building logic in `application/context_builder.py`
- Database persistence via repositories, never direct SQLAlchemy in services
