"""PostgreSQL migration, concurrency, and isolation proof for Stage 7."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.infrastructure.db.repositories import DbEvolutionRepository
from tests.integration.characters.test_continuity_postgres import (
    _chat_snapshot,
    _configuration,
)
from tests.integration.characters.test_evolution_repository import _prepared
from tests.integration.characters.test_stage_seven_acceptance import (
    prove_stage_seven_milestone,
)

pytestmark = pytest.mark.characters_postgres


def test_stage_seven_migrations_concurrency_and_journey_preserve_chat(
    characters_postgres_engine: Engine,
) -> None:
    """Prove Stage 7 on PostgreSQL beside populated private Chat records.

    Args:
        characters_postgres_engine:
            Explicit disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    command.upgrade(_configuration(engine, "chat"), "head")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO chat.conversations "
                "(id,title,requested_generation_configuration,created_at,updated_at) "
                "VALUES ('11111111-1111-1111-1111-111111111111',"
                "'Stage 7 private Chat','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO chat.messages (id,conversation_id,role,content,created_at) "
                "VALUES ('22222222-2222-2222-2222-222222222222',"
                "'11111111-1111-1111-1111-111111111111','user',"
                "'Must remain outside Characters',CURRENT_TIMESTAMP)"
            )
        )
    before = _chat_snapshot(engine)

    configuration = _configuration(engine)
    command.upgrade(configuration, "head")
    command.check(configuration)
    assert _chat_snapshot(engine) == before
    expected_tables = {
        "evolution_effects",
        "evolution_events",
        "evolution_correction_events",
        "relationship_projections",
        "persona_adaptation_projections",
    }
    inspector = inspect(engine)
    assert expected_tables <= set(inspector.get_table_names(schema="characters"))
    for table in expected_tables:
        assert all(
            foreign_key["referred_schema"] == "characters"
            for foreign_key in inspector.get_foreign_keys(table, schema="characters")
        )

    factory = sessionmaker(bind=engine, autoflush=False)
    prove_stage_seven_milestone(factory)
    _prove_concurrent_effect_reservation(factory)

    assert _chat_snapshot(engine) == before


def _prove_concurrent_effect_reservation(factory: sessionmaker[Session]) -> None:
    """Require racing PostgreSQL reservations to return one durable effect.

    Args:
        factory:
            Disposable PostgreSQL Characters sessions.
    """

    _, source, _, _, provenance = _prepared(factory)

    def reserve() -> object:
        """Reserve the shared source from one independent transaction."""

        return DbEvolutionRepository(factory).reserve(source, provenance)

    with ThreadPoolExecutor(max_workers=2) as pool:
        effects = tuple(pool.map(lambda _: reserve(), range(2)))

    assert effects[0] == effects[1]
