import os
from collections.abc import Generator
from sqlite3 import Connection as SQLiteConnection
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    """Create an isolated database session factory for testing.

    An in-memory SQLite database is created for each
    test, ensuring complete test isolation and
    automatic cleanup.

    Yields:
        SQLAlchemy session factory connected to an
        isolated in-memory database.
    """

    from chat_buddy.chat.infrastructure.db import CHAT_SCHEMA, ChatBase

    engine = create_engine(
        "sqlite:///:memory:",
        execution_options={
            "schema_translate_map": {CHAT_SCHEMA: None},
        },
    )

    ChatBase.metadata.create_all(engine)

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
    )

    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def characters_session_factory() -> Generator[sessionmaker[Session], None, None]:
    """Yield a Characters-only SQLite database without importing Chat.

    Yields:
        A session factory with isolated Characters tables.
    """

    from sqlalchemy.pool import StaticPool

    from chat_buddy.characters.infrastructure.db import models  # noqa: F401
    from chat_buddy.characters.infrastructure.db import (
        CHARACTERS_SCHEMA,
        CharactersBase,
    )

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={"schema_translate_map": {CHARACTERS_SCHEMA: None}},
    )
    CharactersBase.metadata.create_all(engine)

    try:
        yield sessionmaker(bind=engine, autoflush=False)
    finally:
        engine.dispose()


@pytest.fixture
def characters_postgres_engine() -> Generator[Engine, None, None]:
    """Create a unique disposable database using an explicit test-only URL.

    Yields:
        An engine whose database is dropped after the test.
    """

    configured_url = os.environ.get("CHARACTERS_TEST_DATABASE_URL")
    if configured_url is None:
        pytest.skip("Set CHARACTERS_TEST_DATABASE_URL to enable PostgreSQL validation")

    url = make_url(configured_url)
    if (
        url.get_backend_name() != "postgresql"
        or not url.database
        or not url.database.endswith("_test")
    ):
        pytest.fail(
            "CHARACTERS_TEST_DATABASE_URL must name a PostgreSQL database ending in _test"
        )

    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    database_name = f"characters_test_{uuid4().hex}"
    engine = create_engine(url.set(database=database_name))
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(
                text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            )
        admin.dispose()


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
    """Enable SQLite foreign-key checks used by repository constraint tests.

    Args:
        dbapi_connection:
            Newly opened DB-API connection.
        _:
            Unused SQLAlchemy connection record.
    """

    if not isinstance(dbapi_connection, SQLiteConnection):
        return

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
