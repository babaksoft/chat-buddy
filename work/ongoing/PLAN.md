## Recommended Stage 1 slices

Each slice should be a separate PR or approval unit. Every slice keeps the application runnable and passes `scripts/check.sh`. Compatibility re-exports temporarily preserve old import paths, then disappear in the final slice.

| Slice | Change | Database impact |
|---|---|---|
| 1A | Add boundaries and guardrails | None |
| 1B | Invert Chat application dependencies | None |
| 1C | Move Chat domain and prompts | None |
| 1D | Move Chat application | None |
| 1E | Move adapters and shared utilities | None |
| 1F | Move Chat persistence code | None |
| 1G | Cut over to the `chat` schema | Development DB reset |
| 1H | Add the `characters` schema | New independent schema |
| 1I | Remove compatibility layer | None |

### 1A — Establish boundaries

- Create empty `chat/`, `characters/`, and `shared/` package structures.
- Move the Characters landing page into `characters/ui/`.
- Keep the Streamlit shell responsible for routing.
- Add an architecture test enforcing:
  - Chat cannot import Characters.
  - Characters cannot import Chat.
  - Shared cannot import either area.
  - The shell may compose both.
- Temporarily allow existing pre-split modules through an explicit legacy-import whitelist.

Acceptance:

- Both navigation areas render.
- Selecting Characters does not initialize Chat services.
- No production behavior or database code changes.

### 1B — Make the existing Chat application infrastructure-independent

Perform this before moving modules so architectural changes are not mixed with file relocation.

- Add Chat repository protocols and persistence-neutral record types.
- Change `ConversationService` and `MemoryService` to depend on protocols instead of concrete SQLAlchemy repositories.
- Require `LLMSummarizer`, `DefaultContextBuilder`, and `MemoryService` dependencies through constructors.
- Build configuration values from infrastructure settings in the composition root.
- Remove all `chat_buddy.infrastructure` imports from the application layer.
- Preserve current behavior and existing Chat dataclass conventions.

Acceptance:

- An import scan finds no infrastructure imports under the application package.
- Existing service tests pass against mocks or protocol-compatible fakes.
- Streamlit behavior remains unchanged.

### 1C — Move Chat domain and prompts

- Move the existing domain modules to `chat_buddy/chat/domain/`.
- Move prompt templates to `chat_buddy/chat/prompts/`.
- Update production imports to the canonical Chat paths.
- Leave thin re-export modules at the old paths for tests or callers not migrated in this slice.
- Do not change model behavior or prompt content.

Acceptance:

- Chat domain and prompts have no imports from application, infrastructure, UI, Shared, or Characters.
- Old and new import paths resolve to the same objects.
- The diff is primarily file moves and import changes.

### 1D — Move the Chat application layer

- Move schemas, configuration values, context building, summarization, and services into `chat_buddy/chat/application/`.
- Update Chat tests to use the new canonical paths.
- Retain temporary re-exports from the old application package.
- Keep UI and infrastructure imports working through those re-exports until their dedicated slices.

Acceptance:

- Application tests run exclusively against the new package.
- The application package imports only Chat domain, Chat prompts, and standard or third-party libraries.
- No user-visible behavior changes.

### 1E — Separate technical utilities and Chat adapters

- Move generic logging setup into `chat_buddy/shared/`.
- Move Chat-specific settings, Ollama adapter, and tokenization implementation into `chat_buddy/chat/infrastructure/`.
- Keep each area’s future gateway contracts in its own domain package.
- Update the composition root to inject the moved adapters.
- Leave compatibility re-exports for old infrastructure import paths.

Acceptance:

- Ollama and context-builder tests pass through the new paths.
- Shared contains no Chat models, prompts, orchestration, or gateway protocols.
- Characters can import Shared without importing or initializing Chat.

### 1F — Namespace Chat persistence code

This slice moves persistence code without changing table locations.

- Move the SQLAlchemy base, models, repositories, engine, and session factory into `chat_buddy/chat/infrastructure/db/`.
- Rename generic persistence symbols where helpful, such as `ChatBase` and `ChatSessionLocal`.
- Update repository, integration, fixture, and composition imports.
- Retain the current public-schema table metadata temporarily.
- Leave compatibility re-exports at the old database paths.

Acceptance:

- Repository and integration tests pass with unchanged persistence behavior.
- Alembic’s legacy environment still discovers the same metadata.
- The diff contains no PostgreSQL schema or migration-history changes.

### 1G — Cut Chat persistence over to the `chat` schema

This is the only destructive approval point.

- Add `schema="chat"` to Chat metadata and schema-qualified foreign keys.
- Add `alembic-chat.ini` with an independent `alembic/chat/` environment.
- Configure `chat.alembic_version`, `include_schemas=True`, and Chat metadata only.
- Add a clean Chat baseline containing the current conversations, messages, and memories tables.
- Adapt SQLite fixtures with `schema_translate_map` while retaining PostgreSQL coverage for real schema behavior.
- Keep existing files under `alembic/versions/` unchanged as legacy history.
- Document the required development-database recreation.

Acceptance:

- A fresh PostgreSQL database upgrades through the Chat migration independently.
- All Chat tables and its version table exist only in `chat`.
- No pre-split rows are mapped or preserved.
- Downgrade and re-upgrade work on a disposable database.

### 1H — Add independent Characters persistence

- Add a Characters SQLAlchemy base, engine/session wiring, and empty model registry.
- Add `alembic-characters.ini` with an independent `alembic/characters/` environment.
- Configure `characters.alembic_version` and Characters metadata only.
- Add an empty baseline that establishes the schema and migration history.
- Do not add identity, persona, or continuity models during Stage 1; those belong to Stage 4.
- Reserve Pydantic for future Characters domain and application models, while SQLAlchemy remains infrastructure-only.

Acceptance:

- Characters migrations run without importing Chat metadata.
- Upgrading Characters does not modify `chat` or `chat.alembic_version`.
- The Characters session can connect without initializing Chat services.

### 1I — Remove transition scaffolding

- Move the Chat page and service composition into `chat_buddy/chat/ui/`.
- Make the top-level Streamlit module a routing-only shell.
- Update every remaining test and utility import to canonical area paths.
- Delete the temporary re-export modules and the legacy-import whitelist.
- Retire the default Alembic target so bare migration commands cannot accidentally use the legacy history; retain the old revision files unchanged for reference.
- Enable strict architecture checks across the entire source tree.

Acceptance:

- No imports remain from the old top-level domain, application, prompts, or infrastructure packages.
- Chat and Characters initialize and test independently.
- Both area-specific migration commands work from a fresh database.
- `scripts/check.sh` passes.
- A PostgreSQL inspection confirms no cross-schema foreign keys or unexpected tables.

The key review strategy is to keep file movement, dependency inversion, and schema changes in separate diffs. Slice 1G should receive dedicated approval because it introduces the development-database reset; all earlier slices preserve the existing database.
