"""Alembic environment for the Characters-owned PostgreSQL schema."""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import Connection, engine_from_config, pool
from sqlalchemy.schema import CreateSchema

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_PATH))

# Import the model registry so future Characters tables attach to the metadata.
import chat_buddy.characters.infrastructure.db.models  # noqa: F401
from chat_buddy.characters.infrastructure.db.base import (
    CHARACTERS_SCHEMA,
    CharactersBase,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = CharactersBase.metadata


def include_name(
    name: str | None,
    type_: str,
    parent_names: dict[str, str | None],
) -> bool:
    """Limit autogeneration inspection to the owned Characters schema."""

    if type_ == "schema":
        return name == CHARACTERS_SCHEMA
    if type_ == "table":
        return parent_names.get("schema_name") == CHARACTERS_SCHEMA
    return True


def configure_context(connection: Connection | None = None) -> None:
    """Configure Alembic with Characters metadata and version storage."""

    options: dict[str, object] = {
        "target_metadata": target_metadata,
        "include_schemas": True,
        "include_name": include_name,
        "version_table": "alembic_version",
        "version_table_schema": CHARACTERS_SCHEMA,
        "compare_type": True,
    }
    if connection is None:
        options.update(
            {
                "url": config.get_main_option("sqlalchemy.url"),
                "literal_binds": True,
                "dialect_opts": {"paramstyle": "named"},
            }
        )
    else:
        options["connection"] = connection

    context.configure(**options)  # type: ignore[arg-type]


def run_migrations_offline() -> None:
    """Emit Characters migration SQL without opening a database connection."""

    configure_context()
    context.execute(f'CREATE SCHEMA IF NOT EXISTS "{CHARACTERS_SCHEMA}"')

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run Characters migrations against PostgreSQL."""

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        connection.execute(CreateSchema(CHARACTERS_SCHEMA, if_not_exists=True))
        connection.commit()
        configure_context(connection)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
