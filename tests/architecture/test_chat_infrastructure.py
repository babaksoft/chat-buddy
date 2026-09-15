"""Architecture checks for the canonical Chat infrastructure adapters."""

import ast
import importlib
from pathlib import Path

import pytest

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


@pytest.mark.parametrize(
    ("legacy_module", "canonical_module", "export_name"),
    [
        (
            "infrastructure.config.logging",
            "shared.config.logging",
            "configure_logging",
        ),
        (
            "infrastructure.llm",
            "chat.infrastructure.llm",
            "OllamaGateway",
        ),
        (
            "infrastructure.tokenization",
            "chat.infrastructure.tokenization",
            "MistralTokenCounter",
        ),
    ],
)
def test_legacy_paths_reexport_canonical_objects(
    legacy_module: str,
    canonical_module: str,
    export_name: str,
) -> None:
    legacy = importlib.import_module(f"chat_buddy.{legacy_module}")
    canonical = importlib.import_module(f"chat_buddy.{canonical_module}")

    assert getattr(legacy, export_name) is getattr(canonical, export_name)


@pytest.mark.parametrize(
    ("legacy_module", "canonical_module", "legacy_name", "canonical_name"),
    [
        (
            "infrastructure.db",
            "chat.infrastructure.db",
            "Base",
            "ChatBase",
        ),
        (
            "infrastructure.db",
            "chat.infrastructure.db",
            "SessionLocal",
            "ChatSessionLocal",
        ),
        (
            "infrastructure.db",
            "chat.infrastructure.db",
            "engine",
            "chat_engine",
        ),
        (
            "infrastructure.db.models",
            "chat.infrastructure.db.models",
            "Conversation",
            "Conversation",
        ),
        (
            "infrastructure.db.models",
            "chat.infrastructure.db.models",
            "Memory",
            "Memory",
        ),
        (
            "infrastructure.db.models",
            "chat.infrastructure.db.models",
            "Message",
            "Message",
        ),
        (
            "infrastructure.db.repositories",
            "chat.infrastructure.db.repositories",
            "ConversationRepository",
            "ConversationRepository",
        ),
        (
            "infrastructure.db.repositories",
            "chat.infrastructure.db.repositories",
            "MemoryRepository",
            "MemoryRepository",
        ),
    ],
)
def test_legacy_database_paths_reexport_canonical_objects(
    legacy_module: str,
    canonical_module: str,
    legacy_name: str,
    canonical_name: str,
) -> None:
    legacy = importlib.import_module(f"chat_buddy.{legacy_module}")
    canonical = importlib.import_module(f"chat_buddy.{canonical_module}")

    assert getattr(legacy, legacy_name) is getattr(canonical, canonical_name)


def test_chat_metadata_uses_the_chat_schema() -> None:
    from chat_buddy.chat.infrastructure.db import CHAT_SCHEMA, ChatBase
    from chat_buddy.chat.infrastructure.db.models import Message

    assert set(ChatBase.metadata.tables) == {
        "chat.conversations",
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
