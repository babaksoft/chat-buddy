# Repository Guidelines

## Project Structure and Architecture

Chat Buddy is a Python 3.12 local-first application with two independent product areas: Chat and Characters. Streamlit provides a thin shared shell. Each area uses domain abstractions, application services, and infrastructure adapters while keeping dependencies pointing inward.

The Stage 1 target layout is:

- `src/chat_buddy/chat/` owns general conversations, provider selection, context management, summaries, Chat memory, prompts, persistence, and UI.
- `src/chat_buddy/characters/` owns identities, personas, continuities, relationship and persona evolution, prompts, persistence, and UI.
- Each area contains its own `domain/`, `application/`, `infrastructure/`, `prompts/`, and `ui/` packages. Domain models and `Protocol` interfaces belong to their owning area.
- `src/chat_buddy/shared/` is limited to generic configuration, logging, and low-level provider utilities. Do not place business rules, prompts, repositories, database models, or area-specific gateway contracts there.
- `src/chat_buddy/ui/streamlit_app.py` is the composition root and may import both areas to route pages. Chat and Characters must not import each other.
- `alembic/chat/` and `alembic/characters/` contain independent migration environments for the PostgreSQL `chat` and `characters` schemas. Existing files in `alembic/versions/` remain unchanged as legacy history.
- `tests/` mirrors the two areas, with cross-layer coverage in `tests/integration/` and architecture checks for area isolation.

Until Stage 1 completes, the existing top-level `domain/`, `application/`, `infrastructure/`, and `prompts/` packages are pre-split Chat code. Move that code into the Chat area rather than extending it with Characters behavior.

Put business rules in application services, persistence only in repositories, and external contracts in the owning area's domain layer. Do not issue direct SQLAlchemy queries from services or UI code. Do not create cross-area imports, cross-schema foreign keys, joins, or repository queries.

## Setup, Running, and Database Changes

Use Python 3.12 and install the locked project and development dependencies with `uv sync --locked`. Dependencies are declared in `pyproject.toml` and frozen in `uv.lock`; use `uv add`, `uv remove`, and their development-group options to change them rather than invoking `pip` or editing the lockfile by hand. Start PostgreSQL using `docker-compose up -d` and run the UI with `uv run streamlit run src/chat_buddy/ui/streamlit_app.py`. Ollama must be available at the configured local endpoint; cloud-provider configuration belongs to its owning area.

During the Stage 1 split, recreate the development database and apply both area baselines; there is no legacy data conversion. After the split, run revisions and upgrades through the area-specific Alembic configuration so Chat changes update only `chat.alembic_version` and Characters changes update only `characters.alembic_version`. For a model change, update the owning area's SQLAlchemy model and repository, generate and review a migration in that area's history, and verify that the other schema is unchanged. Never edit an applied migration.

## Style and Quality Checks

Use four-space indentation, complete type hints on every function, and Google-style docstrings for all classes, methods and functions. In `Args:` and `Raises:` sections, put each item name and its description on separate lines, with the description indented beneath the name. Omit `Args:` when there are no arguments, as well as `Returns:` when a function/method returns `None`. Use absolute package-level imports everywhere; do not use relative imports. Name modules and functions in `snake_case`, classes in `PascalCase`, and tests as `test_<behavior>.py` with `test_<expected_behavior>()` cases. Existing Chat model choices may remain unchanged; prefer frozen, slotted dataclasses for new immutable Chat domain values. In Characters, prefer Pydantic models for domain values and application schemas, configured as frozen when the value is immutable. Keep SQLAlchemy persistence models in the Characters infrastructure layer rather than using them as domain or application models. Give every field on a persistence model a concise `doc` description, including mapped columns and relationships.

Before committing, run the same checks as CI:

```bash
uv run black --check src tests
uv run isort --check-only src tests
uv run ruff check src tests
uv run mypy src tests
uv run pytest -v
# or: scripts/check.sh
```

## Testing and Contributions

Add focused unit tests beside the affected area and layer; add an integration test when a change crosses service and repository boundaries. Add architecture coverage for import and schema isolation when boundaries change. Use shared fixtures from `tests/conftest.py` and keep the full suite passing without requiring unstated local state.

Commit subjects in this repository are short, imperative, and scoped when useful (for example, `Add memory repository` or `Refactor context builder`). Keep each commit cohesive. Pull requests should explain the user-visible or architectural change, list validation run, link the relevant issue when one exists, and include Streamlit screenshots for UI changes. Call out migrations, model/configuration changes, and any required Ollama or database setup explicitly.
