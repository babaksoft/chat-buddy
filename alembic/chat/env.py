import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import Connection, engine_from_config, pool
from sqlalchemy.schema import CreateSchema

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_PATH))

# Import the model registry so all Chat tables are attached to the metadata.
import chat_buddy.chat.infrastructure.db.models  # noqa: F401
from chat_buddy.chat.infrastructure.db.base import (
    CHAT_SCHEMA,
    ChatBase,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = ChatBase.metadata


def include_name(
    name: str | None,
    type_: str,
    parent_names: dict[str, str | None],
) -> bool:
    """Limit autogeneration inspection to the owned Chat schema."""

    if type_ == "schema":
        return name == CHAT_SCHEMA
    if type_ == "table":
        return parent_names.get("schema_name") == CHAT_SCHEMA
    return True


def configure_context(connection: Connection | None = None) -> None:
    """Configure Alembic with Chat-owned metadata and version storage."""

    options: dict[str, object] = {
        "target_metadata": target_metadata,
        "include_schemas": True,
        "include_name": include_name,
        "version_table": "alembic_version",
        "version_table_schema": CHAT_SCHEMA,
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
    """Emit the Chat migration SQL without opening a database connection."""

    configure_context()
    context.execute(f'CREATE SCHEMA IF NOT EXISTS "{CHAT_SCHEMA}"')

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run Chat migrations against PostgreSQL."""

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        connection.execute(CreateSchema(CHAT_SCHEMA, if_not_exists=True))
        connection.commit()
        configure_context(connection)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
