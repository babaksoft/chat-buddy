"""Architecture checks for the canonical Chat infrastructure adapters."""

import ast
from pathlib import Path

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
        "chat.messages",
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


def test_chat_generation_migration_isolated_from_characters() -> None:
    """Verify the Slice 4 migration owns only Chat schema objects."""

    migration = (
        Path(__file__).parents[2]
        / "alembic"
        / "chat"
        / "versions"
        / "82e6c4f63a91_add_generation_persistence.py"
    ).read_text(encoding="utf-8")

    assert 'CHAT_SCHEMA = "chat"' in migration
    assert "characters" not in migration.lower()
