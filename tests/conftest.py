from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.chat.infrastructure.db import CHAT_SCHEMA, ChatBase


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
    """Enable SQLite foreign-key checks used by repository constraint tests.

    Args:
        dbapi_connection:
            Newly opened DB-API connection.
        _:
            Unused SQLAlchemy connection record.
    """

    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    """
    Create an isolated database session factory for testing.

    An in-memory SQLite database is created for each
    test, ensuring complete test isolation and
    automatic cleanup.

    Yields:
        SQLAlchemy session factory connected to an
        isolated in-memory database.
    """

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
