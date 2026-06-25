## Project

Using LlamaIndex with Ollama model, Streamlit front-end, PostgreSQL database managed with SQLAlchemy using Alembic migrations

## Commands

- Format: `black --check .` and `isort --check .`
- Lint: `ruff check .`
- Type check: `mypy .`
- Run tests: `pytest -v`

## Conventions

- Type hints required on all functions
- Google-style docstrings required when they add value
- Automated tests (unit and integration) required
- Tests should not break CI

## Constraints

- Should keep custom prompts organized inside `prompts` package
