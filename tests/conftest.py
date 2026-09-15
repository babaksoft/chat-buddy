from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.chat.infrastructure.db import CHAT_SCHEMA, ChatBase


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """
    Create an isolated database session for testing.

    An in-memory SQLite database is created for each
    test, ensuring complete test isolation and
    automatic cleanup.

    Yields:
        SQLAlchemy session connected to an isolated
        in-memory database.
    """

    engine = create_engine(
        "sqlite:///:memory:",
        execution_options={
            "schema_translate_map": {CHAT_SCHEMA: None},
        },
    )

    ChatBase.metadata.create_all(engine)

    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
    )

    with session_factory() as session:
        yield session
