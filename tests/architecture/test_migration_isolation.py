"""Executable checks for independent area migration histories."""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]


def test_chat_migrations_own_only_chat_schema_objects() -> None:
    """Verify Chat history targets its schema and version table exclusively."""

    sql = _offline_migration_sql("alembic-chat.ini")

    assert 'create schema if not exists "chat"' in sql
    assert "create table chat.alembic_version" in sql
    assert "create table chat.generation_attempts" in sql
    assert "create table chat.summaries" in sql
    assert "create table chat.memory_extraction_receipts" in sql
    assert "characters" not in sql


def test_characters_migrations_remain_independent_from_chat() -> None:
    """Verify Characters history has its own schema and version table only."""

    sql = _offline_migration_sql("alembic-characters.ini")

    assert 'create schema if not exists "characters"' in sql
    assert "create table characters.alembic_version" in sql
    assert "create table characters.identities" in sql
    assert "create table characters.personas" in sql
    assert "create table characters.continuities" in sql
    assert "create table characters.conversations" in sql
    assert "create table characters.starting_relationships" in sql
    assert "create table characters.messages" in sql
    assert "create table characters.generation_attempts" in sql
    assert "create table characters.summary_revisions" in sql
    assert "create unique index uq_open_conversation_attempt" in sql
    assert "create unique index uq_active_conversation_summary" in sql
    assert "create unique index uq_active_ongoing_pair" in sql
    assert "chat." not in sql


def _offline_migration_sql(configuration_name: str) -> str:
    """Render one area's complete migration history as offline SQL.

    Args:
        configuration_name:
            Area-specific Alembic configuration filename.

    Returns:
        SQL emitted for upgrading that area to its head revision.
    """

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            configuration_name,
            "upgrade",
            "head",
            "--sql",
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.lower()
