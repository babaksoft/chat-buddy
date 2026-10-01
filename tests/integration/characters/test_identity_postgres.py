"""PostgreSQL migration and concurrency acceptance for Slice 1."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import VARCHAR, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DataError
from sqlalchemy.orm import sessionmaker

from chat_buddy.characters.application.identity_service import IdentityService
from chat_buddy.characters.domain.errors import StaleIdentityError
from chat_buddy.characters.domain.identity import Identity, IdentityDetails
from chat_buddy.characters.infrastructure.db.models import IdentityModel
from chat_buddy.characters.infrastructure.db.repositories.identity_repository import (
    DbIdentityRepository,
)

pytestmark = pytest.mark.characters_postgres
BASELINE = "61a5c7060ad9"


def test_fresh_upgrade_downgrade_and_reupgrade_preserve_populated_chat(
    characters_postgres_engine: Engine,
) -> None:
    """Exercise both upgrade paths and downgrade without changing Chat.

    Args:
        characters_postgres_engine:
            Engine connected to a disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    command.upgrade(_configuration(engine, "chat"), "head")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO chat.conversations (id,title,requested_generation_configuration,created_at,updated_at) VALUES ('11111111-1111-1111-1111-111111111111','Preserve this Chat conversation','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
    before = _chat_snapshot(engine)
    configuration = _configuration(engine)
    command.upgrade(configuration, "head")
    command.check(configuration)
    assert _chat_snapshot(engine) == before
    service = IdentityService(DbIdentityRepository(sessionmaker(bind=engine)))
    details = IdentityDetails(
        name="Alex",
        gender="nonbinary",
        birth_date=date(1990, 4, 5),
        pronouns="they/them",
        preferred_address="Alex",
        timezone="Asia/Tehran",
    )
    identity = service.create(details)
    assert service.inspect(identity.id).details == details
    service.edit(identity.id, IdentityDetails(name="Alex", age=36), 1)
    assert service.inspect(identity.id).details.age == 36
    assert service.ensure_default() == service.ensure_default()
    inspector = inspect(engine)
    assert inspector.get_table_names(schema="characters") == [
        "alembic_version",
        "identities",
        "personas",
    ]
    assert inspector.get_foreign_keys("identities", schema="characters") == []
    string_lengths = {
        column["name"]: column["type"].length
        for column in inspector.get_columns("identities", schema="characters")
        if isinstance(column["type"], VARCHAR)
    }
    assert string_lengths == {
        "name": 128,
        "gender": 64,
        "pronouns": 64,
        "preferred_address": 128,
        "timezone": 64,
        "default_key": 3,
    }
    maximum_details = IdentityDetails(
        name="n" * 128,
        gender="g" * 64,
        pronouns="p" * 64,
        preferred_address="a" * 128,
        timezone="Asia/Tehran",
    )
    maximum_identity = service.create(maximum_details)
    assert service.inspect(maximum_identity.id).details == maximum_details
    for field, length in string_lengths.items():
        assert length is not None
        with (
            pytest.raises(DataError),
            sessionmaker(bind=engine)() as session,
            session.begin(),
        ):
            session.add(IdentityModel(**{"name": "You", field: "x" * (length + 1)}))
            session.flush()
    command.downgrade(configuration, BASELINE)
    assert inspect(engine).get_table_names(schema="characters") == ["alembic_version"]
    assert _chat_snapshot(engine) == before
    command.upgrade(configuration, "head")
    command.check(configuration)
    assert service.list() == []
    assert _chat_snapshot(engine) == before


def test_concurrent_default_setup_returns_one_identity(
    characters_postgres_engine: Engine,
) -> None:
    """Force two absent-default reads before either transaction inserts.

    Args:
        characters_postgres_engine:
            Engine connected to a disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    command.upgrade(_configuration(engine), "head")
    barrier = Barrier(2)

    def synchronize_inserts(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        """Synchronize default inserts to exercise uniqueness conflict recovery.

        Args:
            connection:
                SQLAlchemy connection.
            cursor:
                DB-API cursor.
            statement:
                SQL about to execute.
            parameters:
                Bound SQL parameters.
            context:
                Execution context.
            executemany:
                Whether this is a batch operation.
        """

        if statement.startswith("INSERT INTO characters.identities"):
            barrier.wait(timeout=10)

    event.listen(engine, "before_cursor_execute", synchronize_inserts)
    service = IdentityService(DbIdentityRepository(sessionmaker(bind=engine)))
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(service.ensure_default) for _ in range(2)]
            identities = [future.result(timeout=20) for future in futures]
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_inserts)
    assert identities[0] == identities[1]
    assert service.list() == [identities[0]]
    assert service.ensure_default() == identities[0]


def test_concurrent_edits_allow_one_revision_winner(
    characters_postgres_engine: Engine,
) -> None:
    """Conditional repository writes reject competing stale revisions.

    Args:
        characters_postgres_engine:
            Engine connected to a disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    command.upgrade(_configuration(engine), "head")
    repository = DbIdentityRepository(sessionmaker(bind=engine))
    identity = repository.create(IdentityDetails(name="Original"))
    barrier = Barrier(2)

    def edit(name: str) -> Identity | StaleIdentityError:
        """Try an edit after both callers have observed the original revision.

        Args:
            name:
                Competing replacement name.

        Returns:
            The winning snapshot or typed stale failure.
        """

        barrier.wait(timeout=10)
        try:
            return repository.replace(identity.id, IdentityDetails(name=name), 1)
        except StaleIdentityError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(edit, ["A", "B"]))
    winners = [outcome for outcome in outcomes if isinstance(outcome, Identity)]
    assert len(winners) == 1
    assert sum(isinstance(outcome, StaleIdentityError) for outcome in outcomes) == 1
    assert repository.get(identity.id) == winners[0]
    assert winners[0].revision == 2


def _configuration(engine: Engine, area: str = "characters") -> Config:
    """Point an area's migrations at the disposable database.

    Args:
        engine:
            Disposable PostgreSQL engine.
        area:
            Area whose migration history should run.

    Returns:
        A database-specific Alembic configuration.
    """

    configuration = Config(f"alembic-{area}.ini")
    configuration.set_main_option(
        "sqlalchemy.url",
        engine.url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    return configuration


def _chat_snapshot(
    engine: Engine,
) -> tuple[list[Any], list[Any], list[Any], dict[str, list[str]]]:
    """Capture Chat objects, columns, constraints, and every persisted row.

    Args:
        engine:
            Engine holding the independent Chat schema.

    Returns:
        Comparable schema and row snapshots, including the version table.
    """

    with engine.connect() as connection:
        objects = list(
            connection.execute(
                text(
                    "SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='chat' ORDER BY 1,2"
                )
            )
        )
        columns = list(
            connection.execute(
                text(
                    "SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema='chat' ORDER BY table_name, ordinal_position"
                )
            )
        )
        constraints = list(
            connection.execute(
                text(
                    "SELECT c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='chat' ORDER BY 1,2"
                )
            )
        )
        rows = {
            table: sorted(
                connection.execute(
                    text(f'SELECT row_to_json(t)::text FROM chat."{table}" t')
                ).scalars()
            )
            for table in inspect(connection).get_table_names(schema="chat")
        }
        return objects, columns, constraints, rows
