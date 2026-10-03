"""PostgreSQL persona migration and concurrent edit acceptance for Slice 2."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import VARCHAR, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DataError
from sqlalchemy.orm import sessionmaker

from chat_buddy.characters.application import PersonaService
from chat_buddy.characters.domain import Persona, PersonaCore, StalePersonaError
from chat_buddy.characters.infrastructure.db.models import PersonaModel
from chat_buddy.characters.infrastructure.db.repositories import (
    DbPersonaRepository,
)

pytestmark = pytest.mark.characters_postgres
PRIOR_HEAD = "d9fa8117ca0c"


def test_persona_migration_paths_preserve_identity_and_populated_chat(
    characters_postgres_engine: Engine,
) -> None:
    """Verify fresh/prior-head upgrades, reversal, limits, and area isolation.

    Args:
        characters_postgres_engine:
            Engine connected to a disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    command.upgrade(_configuration(engine, "chat"), "head")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO chat.conversations (id,title,requested_generation_configuration,created_at,updated_at) VALUES ('11111111-1111-1111-1111-111111111111','Keep Chat','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
    before = _chat_snapshot(engine)
    configuration = _configuration(engine)
    command.upgrade(configuration, "head")
    command.check(configuration)
    assert _chat_snapshot(engine) == before
    service = PersonaService(DbPersonaRepository(sessionmaker(bind=engine)))
    core = PersonaCore(name="n" * 128, definition="d" * 8192, traits="t" * 4096)
    source = service.create(core)
    assert service.inspect(source.id).core == core
    inspector = inspect(engine)
    assert inspector.get_foreign_keys("personas", schema="characters") == []
    lengths = {
        column["name"]: column["type"].length
        for column in inspector.get_columns("personas", schema="characters")
        if isinstance(column["type"], VARCHAR)
    }
    assert lengths == {"name": 128, "definition": 8192, "traits": 4096}
    for field, length in lengths.items():
        assert length is not None
        with (
            pytest.raises(DataError),
            sessionmaker(bind=engine)() as session,
            session.begin(),
        ):
            session.add(
                PersonaModel(
                    **{"name": "A", "definition": "Guide", field: "x" * (length + 1)}
                )
            )
            session.flush()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO characters.identities (id,name,revision,is_frozen) VALUES ('22222222-2222-2222-2222-222222222222','Keep identity',1,false)"
            )
        )
    command.downgrade(configuration, PRIOR_HEAD)
    assert inspect(engine).get_table_names(schema="characters") == [
        "alembic_version",
        "identities",
    ]
    command.upgrade(configuration, "head")
    command.check(configuration)
    assert service.list() == []
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT name FROM characters.identities")
            ).scalar_one()
            == "Keep identity"
        )
    assert _chat_snapshot(engine) == before


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
    repository = DbPersonaRepository(sessionmaker(bind=engine))
    persona = repository.create(PersonaCore(name="Original", definition="Guide"))
    barrier = Barrier(2)

    def edit(name: str) -> Persona | StalePersonaError:
        """Try an edit after both callers have observed the original revision.

        Args:
            name:
                Competing replacement name.

        Returns:
            The winning snapshot or typed stale failure.
        """

        barrier.wait(timeout=10)
        try:
            return repository.replace(
                persona.id, PersonaCore(name=name, definition=name), 1
            )
        except StalePersonaError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(edit, ["A", "B"]))
    winners = [outcome for outcome in outcomes if isinstance(outcome, Persona)]
    assert len(winners) == 1
    assert sum(isinstance(outcome, StalePersonaError) for outcome in outcomes) == 1
    assert repository.get(persona.id) == winners[0]
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
