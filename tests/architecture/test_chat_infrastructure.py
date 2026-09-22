"""Architecture checks for the canonical Chat infrastructure adapters."""

import ast
import inspect
from pathlib import Path
from typing import get_args, get_origin, get_type_hints

from sqlalchemy.orm import Session, sessionmaker

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "chat_buddy"
CHAT_INFRASTRUCTURE_ROOT = PACKAGE_ROOT / "chat" / "infrastructure"
ALLOWED_CHAT_DEPENDENCIES = (
    "chat_buddy.chat.domain",
    "chat_buddy.chat.infrastructure",
    "chat_buddy.chat.prompts",
    "chat_buddy.shared",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }


def test_chat_adapters_depend_only_on_owned_or_shared_packages() -> None:
    violations = [
        f"{path.relative_to(PACKAGE_ROOT)} imports {imported_module}"
        for path in sorted(CHAT_INFRASTRUCTURE_ROOT.rglob("*.py"))
        for imported_module in sorted(_imports(path))
        if imported_module.startswith("chat_buddy.")
        and not imported_module.startswith(ALLOWED_CHAT_DEPENDENCIES)
    ]

    assert violations == []


def test_chat_metadata_uses_the_chat_schema() -> None:
    """Verify every Chat persistence model belongs only to the Chat schema."""

    from chat_buddy.chat.infrastructure.db import CHAT_SCHEMA, ChatBase
    from chat_buddy.chat.infrastructure.db.models import GenerationAttempt, Message

    assert set(ChatBase.metadata.tables) == {
        "chat.conversations",
        "chat.generation_attempts",
        "chat.memories",
        "chat.memory_extraction_receipts",
        "chat.messages",
        "chat.summaries",
    }
    assert all(
        table.schema == CHAT_SCHEMA for table in ChatBase.metadata.tables.values()
    )
    assert {key.target_fullname for key in Message.__table__.foreign_keys} == {
        "chat.conversations.id"
    }
    assert getattr(Message.__table__.c.role.type, "schema", None) == CHAT_SCHEMA
    assert {
        key.target_fullname for key in GenerationAttempt.__table__.foreign_keys
    } == {
        "chat.conversations.id",
        "chat.messages.conversation_id",
        "chat.messages.id",
    }


def test_chat_persistence_fields_have_descriptions() -> None:
    """Verify every mapped Chat field has a concise description."""

    from chat_buddy.chat.infrastructure.db import ChatBase

    undocumented_fields = sorted(
        f"{mapper.class_.__name__}.{attribute.key}"
        for mapper in ChatBase.registry.mappers
        for attribute in mapper.attrs
        if not attribute.doc
    )

    assert undocumented_fields == []


def test_generation_attempt_persistence_has_a_dedicated_adapter() -> None:
    """Keep attempt lifecycle methods off the conversation adapter."""

    from chat_buddy.chat.infrastructure.db.repositories import (
        ConversationRepository,
        GenerationAttemptRepository,
    )

    lifecycle_methods = (
        "start_generation_attempt",
        "retry_generation_attempt",
        "begin_generation_attempt",
        "checkpoint_generation_attempt",
        "complete_generation_attempt",
        "fail_generation_attempt",
        "interrupt_generation_attempt",
        "get_generation_attempt",
        "get_open_generation_attempt",
        "get_latest_retryable_generation_attempt",
        "get_generation_attempts",
    )

    assert all(
        not hasattr(ConversationRepository, method) for method in lifecycle_methods
    )
    assert all(
        hasattr(GenerationAttemptRepository, method) for method in lifecycle_methods
    )


def test_chat_repositories_require_session_factories() -> None:
    """Prevent concrete repositories from regaining live-session constructors."""

    from chat_buddy.chat.infrastructure.db.repositories import (
        ConversationRepository,
        GenerationAttemptRepository,
        MemoryRepository,
        SummaryRepository,
    )

    repositories = (
        ConversationRepository,
        GenerationAttemptRepository,
        MemoryRepository,
        SummaryRepository,
    )

    for repository in repositories:
        parameters = tuple(inspect.signature(repository).parameters.values())
        session_factory_annotation = get_type_hints(repository.__init__)[
            "session_factory"
        ]
        assert len(parameters) == 1
        assert parameters[0].name == "session_factory"
        assert get_origin(session_factory_annotation) is sessionmaker
        assert get_args(session_factory_annotation) == (Session,)


def test_chat_composition_passes_factory_without_opening_sessions() -> None:
    """Keep SQLAlchemy session creation inside concrete repositories."""

    composition_path = PACKAGE_ROOT / "chat" / "ui" / "composition.py"
    tree = ast.parse(
        composition_path.read_text(encoding="utf-8-sig"),
        filename=str(composition_path),
    )
    opened_sessions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ChatSessionLocal"
    ]

    assert opened_sessions == []


def test_chat_generation_migration_isolated_from_characters() -> None:
    """Verify the Stage 2 generation migration owns only Chat objects."""

    migration = (
        Path(__file__).parents[2]
        / "alembic"
        / "chat"
        / "versions"
        / "82e6c4f63a91_add_generation_persistence.py"
    ).read_text(encoding="utf-8")

    assert 'CHAT_SCHEMA = "chat"' in migration
    assert "characters" not in migration.lower()


def test_stage_three_persistence_migration_isolated_from_characters() -> None:
    """Verify the Slice 3 migration owns only Chat schema objects."""

    migration = (
        Path(__file__).parents[2]
        / "alembic"
        / "chat"
        / "versions"
        / "d4a9f12c6b30_persist_summary_and_memory_lifecycle.py"
    ).read_text(encoding="utf-8")

    assert 'CHAT_SCHEMA = "chat"' in migration
    assert "characters" not in migration.lower()
