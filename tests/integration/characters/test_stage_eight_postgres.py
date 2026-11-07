"""PostgreSQL migration and area-isolation proof for Stage 8."""

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from tests.integration.characters.test_continuity_postgres import (
    _chat_snapshot,
    _configuration,
)
from tests.integration.characters.test_stage_eight_acceptance import (
    prove_stage_eight_milestone,
)
from tests.integration.characters.test_timeline_evolution_postgres import (
    test_concurrent_timeline_inference_commits_one_effect_and_event as _prove_concurrent_evolution,
)
from tests.integration.characters.test_timeline_postgres import (
    test_two_first_sends_create_one_atomic_day as _prove_concurrent_first_send,
)

pytestmark = pytest.mark.characters_postgres


def test_stage_eight_chain_journey_and_concurrency_preserve_populated_chat(
    characters_postgres_engine: Engine,
) -> None:
    """Prove Stage 8 on PostgreSQL beside populated private Chat records.

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
                "'Stage 8 private Chat','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
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
        "continuity_entries",
        "continuity_memories",
        "evolution_effects",
        "evolution_events",
        "persona_adaptation_projections",
        "relationship_projections",
        "response_style_settings",
        "timeline_days",
        "timelines",
    }
    inspector = inspect(engine)
    assert expected_tables <= set(inspector.get_table_names(schema="characters"))
    for table in expected_tables:
        assert all(
            foreign_key["referred_schema"] == "characters"
            for foreign_key in inspector.get_foreign_keys(table, schema="characters")
        )

    factory = sessionmaker(bind=engine, autoflush=False)
    _prove_concurrent_first_send(engine)
    prove_stage_eight_milestone(factory)
    _prove_concurrent_evolution(engine)

    assert _chat_snapshot(engine) == before
