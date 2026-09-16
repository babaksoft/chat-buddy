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
