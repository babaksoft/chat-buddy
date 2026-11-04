"""PostgreSQL migration coverage for Entry-backed evolution provenance."""

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from tests.integration.characters.test_continuity_entry_postgres import (
    _insert_prior_head_entries,
)
from tests.integration.characters.test_continuity_postgres import _configuration

pytestmark = pytest.mark.characters_postgres
PRIOR_HEAD = "4b8e2d7c1a90"


def test_evolution_migration_preserves_exact_storyline_entry_provenance(
    characters_postgres_engine: Engine,
) -> None:
    """Normalize and restore representative Storyline evolution evidence.

    Args:
        characters_postgres_engine:
            Explicit disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    configuration = _configuration(engine)
    command.upgrade(configuration, "d6e8f1a2b3c4")
    _insert_prior_head_entries(engine)
    command.upgrade(configuration, PRIOR_HEAD)
    _insert_prior_evolution_effect(engine)

    command.upgrade(configuration, "head")
    command.check(configuration)
    _assert_entry_evidence(engine)

    command.downgrade(configuration, PRIOR_HEAD)
    _assert_scene_evidence(engine)
    command.upgrade(configuration, "head")
    command.check(configuration)
    _assert_entry_evidence(engine)


def _insert_prior_evolution_effect(engine: Engine) -> None:
    """Insert one reserved effect using the preceding Scene vocabulary.

    Args:
        engine:
            Disposable PostgreSQL engine at the prior head.
    """

    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO characters.messages
                (id, conversation_id, continuity_id, role, content,
                 parent_id, response_provenance, created_at)
            VALUES
                ('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
                 '88888888-8888-8888-8888-888888888888',
                 '44444444-4444-4444-4444-444444444444', 'persona',
                 'Story response', 'cccccccc-cccc-cccc-cccc-cccccccccccc',
                 '{}', CURRENT_TIMESTAMP);
            UPDATE characters.conversations
            SET selected_leaf_id = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
            WHERE id = '88888888-8888-8888-8888-888888888888';
            INSERT INTO characters.evolution_effects
                (id, continuity_id, identity_id, persona_id, conversation_id,
                 source_persona_message_id, source, state, provenance, proposal,
                 decision, created_at, completed_at)
            VALUES
                ('10000000-0000-0000-0000-000000000001',
                 '44444444-4444-4444-4444-444444444444',
                 '22222222-2222-2222-2222-222222222222',
                 '33333333-3333-3333-3333-333333333333',
                 '88888888-8888-8888-8888-888888888888',
                 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
                 '{"scope":{"identity_id":"22222222-2222-2222-2222-222222222222",'
                 '"persona_id":"33333333-3333-3333-3333-333333333333",'
                 '"continuity_id":"44444444-4444-4444-4444-444444444444"},'
                 '"kind":"storyline_checkpoint",'
                 '"conversation_id":"88888888-8888-8888-8888-888888888888",'
                 '"scene_id":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",'
                 '"scene_position":1,'
                 '"user_message_id":"cccccccc-cccc-cccc-cccc-cccccccccccc",'
                 '"user_sequence":1,'
                 '"persona_message_id":"eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",'
                 '"persona_sequence":2}',
                 'reserved', '{}', NULL, NULL, CURRENT_TIMESTAMP, NULL);
            """))


def _assert_entry_evidence(engine: Engine) -> None:
    """Assert relational and serialized Entry provenance after upgrade.

    Args:
        engine:
            Disposable PostgreSQL engine at the new head.
    """

    columns = {
        column["name"]
        for column in inspect(engine).get_columns(
            "evolution_effects", schema="characters"
        )
    }
    assert {"evidence_kind", "entry_id"} <= columns
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT evidence_kind, entry_id::text, source->>'kind', "
                "source#>>'{entry,entry_id}', source#>>'{entry,position}' "
                "FROM characters.evolution_effects"
            )
        ).one()
    assert row == (
        "entry_checkpoint",
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "entry_checkpoint",
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "1",
    )


def _assert_scene_evidence(engine: Engine) -> None:
    """Assert downgrade restores exact serialized Scene provenance.

    Args:
        engine:
            Disposable PostgreSQL engine at the prior head.
    """

    columns = {
        column["name"]
        for column in inspect(engine).get_columns(
            "evolution_effects", schema="characters"
        )
    }
    assert {"evidence_kind", "entry_id"}.isdisjoint(columns)
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT source->>'kind', source->>'scene_id', "
                "source->>'scene_position' FROM characters.evolution_effects"
            )
        ).one()
    assert row == (
        "storyline_checkpoint",
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "1",
    )
