# Repository Guidelines

## Project Structure and Architecture

Chat Buddy is a Python 3.12 local-first application with two independent product areas: Chat and Characters. Streamlit provides a thin shared shell. Each area uses domain abstractions, application services, and infrastructure adapters while keeping dependencies pointing inward.

The target layout is:

- `src/chat_buddy/chat/` owns general conversations, provider selection, context management, summaries, Chat memory, prompts, persistence, and UI.
- `src/chat_buddy/characters/` owns identities, personas, continuities, relationship and persona evolution, prompts, persistence, and UI.
- Each area contains its own `domain/`, `application/`, `infrastructure/`, `prompts/`, and `ui/` packages. Domain models and `Protocol` interfaces belong to their owning area.
- `src/chat_buddy/shared/` is limited to generic configuration, logging, and low-level provider utilities. Do not place business rules, prompts, repositories, database models, or area-specific gateway contracts there.
- `src/chat_buddy/ui/streamlit_app.py` is the composition root and may import both areas to route pages. Chat and Characters must not import each other.
- `alembic/chat/` and `alembic/characters/` contain independent migration environments for the PostgreSQL `chat` and `characters` schemas. Existing files in `alembic/versions/` remain unchanged as legacy history.
- `tests/` mirrors the two areas, with cross-layer coverage in `tests/integration/` and architecture checks for area isolation.

Put business rules in application services, persistence only in repositories, and external contracts in the owning area's domain layer. Do not issue direct SQLAlchemy queries from services or UI code. Do not create cross-area imports, cross-schema foreign keys, joins, or repository queries.

## Setup, Running, and Database Changes

Use Python 3.12 and install the locked project and development dependencies with `uv sync --locked`. Dependencies are declared in `pyproject.toml` and frozen in `uv.lock`; use `uv add`, `uv remove`, and their development-group options to change them rather than invoking `pip` or editing the lockfile by hand. Start PostgreSQL using `docker-compose up -d` and run the UI with `uv run streamlit run src/chat_buddy/ui/streamlit_app.py`. Ollama must be available at the configured local endpoint; cloud-provider configuration belongs to its owning area.

During the Stage 1 split, recreate the development database and apply both area baselines; there is no legacy data conversion. After the split, run revisions and upgrades through the area-specific Alembic configuration so Chat changes update only `chat.alembic_version` and Characters changes update only `characters.alembic_version`. For a model change, update the owning area's SQLAlchemy model and repository, generate and review a migration in that area's history, and verify that the other schema is unchanged. Never edit an applied migration.

## Style and Quality Checks

- Use four-space indentation.
- Add complete type hints to every function.
- Add complete Google-style docstrings to every class, method, and function.
- In `Args:` and `Raises:` sections, put each item name on its own line and indent
  its description beneath it.
- Omit `Args:` when there are no arguments. Omit `Returns:` when a function or
  method returns `None`.
- Always add a single blank line after docstrings.
- Use absolute package-level imports everywhere; do not use relative imports.
- Export main architecture types and symbols at their owning package boundary
  (`__init__.py`).
- Import main architecture types and symbols from their owning package boundary,
  except when used inside the same package.
- Name modules and functions in `snake_case`, classes in `PascalCase`, test modules
  as `test_<behavior>.py`, and test cases as `test_<expected_behavior>()`.
- Prefix new database-backed repository implementation classes with `Db`
  (for example, `DbIdentityRepository`). Keep domain repository protocol names
  unprefixed (for example, `IdentityRepository`).
- Choose sensible, purpose-specific limits for variable-length string columns
  (`VARCHAR`/`NVARCHAR`), preferably multiples of 16, and match authored-field
  domain validation limits to persistence limits. Exact bounded internal values
  may use their known length (for example, `default_key` uses 3). This guideline
  applies to variable-length strings only.
- Give every field on a persistence model a concise `doc` description, including
  mapped columns and relationships.
- Use Pydantic models for domain values and application schemas, configured as frozen
  when the value is immutable.
- Give every new Pydantic model a complete Google-style `Attributes:` section and
  every field a `description` argument.
- Prefer putting internal functions/methods at the bottom and adding
  `from __future__ import annotations` if required.

Before committing, run the same checks as CI:

```bash
timeout 30s uv run black --check src tests
uv run isort --check-only src tests
uv run ruff check src tests
uv run mypy src tests
uv run pytest -v
```

Cap every Black invocation at 30 seconds. If Black times out, do not retry it or
allow it to delay the task; continue running the other checks independently and
report the incomplete Black run in the final handoff. A timeout is not a successful
format check. The developer may rerun Black separately with their local uv cache.
Treat formatting failures returned within the time limit normally: fix them and
rerun once with the same cap. `scripts/check.sh` remains available for local use,
but do not use it when its uncapped Black step could prevent the remaining checks
from running.

## Testing and Contributions

Add focused unit tests beside the affected area and layer; add an integration test when a change crosses service and repository boundaries. Add architecture coverage for import and schema isolation when boundaries change. Use shared fixtures from `tests/conftest.py` and keep the full suite passing without requiring unstated local state.

Commit subjects in this repository are short, imperative, and scoped when useful (for example, `Add memory repository` or `Refactor context builder`). Keep each commit cohesive. Pull requests should explain the user-visible or architectural change, list validation run, link the relevant issue when one exists, and include Streamlit screenshots for UI changes. Call out migrations, model/configuration changes, and any required Ollama or database setup explicitly.

## README Maintenance

Treat `README.md` as the stable, reviewer-facing product overview and onboarding
guide. Keep it useful to someone evaluating or running the application without
requiring knowledge of the delivery history.

Preserve its standard organization: product introduction, current Chat and
Characters capabilities, product scope, local/cloud data behavior, architecture
overview, technology stack, quick start, configuration, database management,
development checks, documentation map, and license. Do not add a table of contents
unless explicitly requested. Add or reorganize major sections only when the
reader's workflow materially changes, not as part of routine feature delivery.

Update the README when a change affects any of the following:

- User-visible capabilities or stable product limitations.
- Prerequisites, installation, migration, startup, or first-use steps.
- Supported operator-facing configuration, its defaults, or provider setup.
- Local versus external data flow, privacy expectations, or billable integrations.
- The high-level area boundary, runtime architecture, or technology stack.
- Commands, paths, links, or document roles shown in the README.

Do not update the README merely to record stage or slice progress, an internal
refactor, a new migration revision identifier, a service/repository API, or a test
matrix. Keep delivery status and future work in `PLAN.md` or the applicable stage
plan; implementation and domain detail in `DESIGN.md`; behavioral decisions and
rationale in `docs/decisions/`; repository conventions in `AGENTS.md`; and
method-level contracts in source docstrings. Describe only shipped behavior as a
feature. If a current limitation matters to users, state it without roadmap or
stage terminology.

When editing the README:

- Keep one canonical setup path and link back to it instead of repeating commands
  in feature sections.
- Verify every command, path, environment variable, default value, model name, and
  feature claim against the current repository. Never present a source constant as
  environment-configurable.
- Keep the technology table limited to components materially used by the current
  application; dependency presence alone is insufficient.
- Keep architecture content conceptual. Do not add class names, method walkthroughs,
  migration inventories, concurrency cases, or exhaustive domain rules.
- Clearly label optional, networked, billable, destructive, or data-sharing actions.
  Never include real credentials or unstated local prerequisites.
- Keep Chat and Characters setup, configuration, persistence, and data-flow claims
  distinct. Do not imply cross-area sharing.
- Use relative repository links, concise tables, and short examples. Preserve the
  scannable overview rather than appending release notes to the end.
- Retain only the operational warning that the root Alembic configuration and
  `alembic/versions/` history are abandoned; do not add historical schema or data
  conversion narratives.
- Run `git diff --check -- README.md` after edits and run broader checks when an
  asserted command or behavior changed with code.

## Design Document Maintenance

Treat `DESIGN.md` as the living source of truth for the system's intended product
behavior, domain model, ownership boundaries, and architectural constraints. It may
describe accepted target behavior that is not delivered yet; use `README.md` for
currently available user-facing behavior and `PLAN.md` for delivery status.

Preserve these top-level sections and their order:

1. Purpose and scope.
2. Design goals and constraints.
3. System context.
4. Architecture and dependency rules.
5. Domain model and invariants.
6. Behavioral design.
7. Data ownership and persistence.
8. External interfaces and integrations.
9. Cross-cutting concerns.
10. Related documents.

Use subsections only to make those essential sections easier to navigate. Add a new
top-level section only when the existing structure genuinely cannot express a
durable design concern, and consolidate overlapping content instead of appending a
parallel explanation elsewhere.

Update the design document when an accepted change affects any of the following:

- Product-area purpose, scope, ownership, or isolation.
- Domain terminology, entity relationships, invariants, lifecycle, or state
  transitions.
- A stable user workflow whose behavior matters across implementations.
- Context eligibility, temporal or branch rules, derived state, or provenance.
- Layer responsibilities, dependency direction, composition, or extension points.
- Data ownership, transaction boundaries, consistency, retention, or deletion.
- External capability contracts, trust boundaries, or provider substitution.
- Security, privacy, reliability, recovery, capacity, observability, or durable UX
  principles that constrain implementation.

Do not update `DESIGN.md` merely to record stage or slice progress, a file move, a
class or method signature, a migration revision, a test case, setup commands, an
environment-variable default, or temporary implementation mechanics. Put delivery
sequence and verification in `PLAN.md` or the applicable work plan; setup and
operator configuration in `README.md`; decision history and rationale in ADRs;
repository conventions in `AGENTS.md`; and method-level contracts in source
docstrings.

When editing the design document:

- Reconcile the change with all accepted ADRs. If behavior changes an accepted
  decision, add or supersede the ADR and update the design in the same change.
- State the resulting design directly. Link to an ADR for rationale rather than
  copying its context and alternatives.
- Do not annotate features with implementation stages, completion markers, or
  temporary status notes. The plan determines what has shipped.
- Keep current and target semantics internally consistent. Do not describe an
  interim implementation limitation as a permanent invariant unless it is an
  accepted product constraint.
- Prefer domain language and observable behavior over framework, table, class, or
  function details. Include exact limits or vocabularies only when they are stable
  behavioral contracts.
- Keep diagrams conceptual, small, and synchronized with the surrounding text.
- Describe Chat and Characters independently and preserve the prohibition on
  cross-area imports, records, queries, prompts, and business rules.
- Replace or remove superseded statements instead of accumulating historical
  narratives. The document should read as one coherent design, not a changelog.
- Check nearby sections for duplicated or conflicting rules whenever an invariant
  changes, especially context, persistence, branching, lifecycle, and recovery.
- Update the `Last updated` date for a material design change, verify relative
  links, and run `git diff --check -- DESIGN.md`. Run relevant tests when a design
  edit accompanies code, but documentation-only formatting does not require the
  code suite.

## ADR Writing

Keep new and updated ADRs concise and minimal. State the behavioral decision and
its rationale in plain language. Put implementation details, slice assignments,
and verification procedures in the master or stage plans. Apply this rule when
adding or updating an ADR; do not rewrite otherwise untouched ADRs solely for style.
