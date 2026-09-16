"""Architecture checks for Characters persistence infrastructure."""

import ast
from pathlib import Path

from sqlalchemy import create_engine, text

from chat_buddy.characters.infrastructure.db import (
    CHARACTERS_SCHEMA,
    CharactersBase,
    CharactersSessionLocal,
)
from chat_buddy.chat.infrastructure.db import ChatBase

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "chat_buddy"
CHARACTERS_INFRASTRUCTURE_ROOT = PACKAGE_ROOT / "characters" / "infrastructure"
CHARACTERS_MIGRATION_ENV = (
    Path(__file__).parents[2] / "alembic" / "characters" / "env.py"
)
ALLOWED_CHARACTERS_DEPENDENCIES = (
    "chat_buddy.characters",
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


def test_characters_adapters_depend_only_on_owned_or_shared_packages() -> None:
    violations = [
        f"{path.relative_to(PACKAGE_ROOT)} imports {imported_module}"
        for path in sorted(CHARACTERS_INFRASTRUCTURE_ROOT.rglob("*.py"))
        for imported_module in sorted(_imports(path))
        if imported_module.startswith("chat_buddy.")
        and not imported_module.startswith(ALLOWED_CHARACTERS_DEPENDENCIES)
    ]

    assert violations == []


def test_characters_migrations_do_not_import_chat_metadata() -> None:
    chat_imports = {
        imported_module
        for imported_module in _imports(CHARACTERS_MIGRATION_ENV)
        if imported_module == "chat_buddy.chat"
        or imported_module.startswith("chat_buddy.chat.")
    }

    assert chat_imports == set()


def test_characters_metadata_is_empty_and_independent() -> None:
    assert CharactersBase.metadata.schema == CHARACTERS_SCHEMA
    assert CharactersBase.metadata.tables == {}
    assert CharactersBase.metadata is not ChatBase.metadata


def test_characters_session_connects_without_chat_services() -> None:
    engine = create_engine("sqlite:///:memory:")

    with CharactersSessionLocal(bind=engine) as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1
