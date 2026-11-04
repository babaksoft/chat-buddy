"""PostgreSQL migration acceptance for normalized Continuity Entries."""

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from tests.integration.characters.test_continuity_postgres import (
    _chat_snapshot,
    _configuration,
)

pytestmark = pytest.mark.characters_postgres
PRIOR_HEAD = "d6e8f1a2b3c4"


def test_entry_migration_preserves_subtypes_and_chat_through_round_trip(
    characters_postgres_engine: Engine,
) -> None:
    """Backfill exact Entry ownership, downgrade, and re-upgrade in isolation.

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
                "'Preserve Chat','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
    before = _chat_snapshot(engine)
    configuration = _configuration(engine)
    command.upgrade(configuration, PRIOR_HEAD)
    _insert_prior_head_entries(engine)

    command.upgrade(configuration, "head")
    command.check(configuration)
    _assert_normalized_entries(engine)
    assert _chat_snapshot(engine) == before

    command.downgrade(configuration, PRIOR_HEAD)
    _assert_denormalized_entries(engine)
    command.upgrade(configuration, "head")
    command.check(configuration)
    _assert_normalized_entries(engine)
    assert _chat_snapshot(engine) == before


def _insert_prior_head_entries(engine: Engine) -> None:
    """Insert representative Scene and Day graphs at the preceding head.

    Args:
        engine:
            Disposable PostgreSQL engine at the prior Characters head.
    """

    with engine.begin() as connection:
        connection.execute(text("""
                INSERT INTO characters.identities (id, name, revision, is_frozen)
                VALUES ('22222222-2222-2222-2222-222222222222', 'Identity', 1, true);
                INSERT INTO characters.personas
                    (id, name, definition, revision, is_frozen)
                VALUES
                    ('33333333-3333-3333-3333-333333333333', 'Persona', 'Definition', 1, true);
                INSERT INTO characters.continuities
                    (id, identity_id, persona_id, mode, lifecycle, request_id, confirmed_request)
                VALUES
                    ('44444444-4444-4444-4444-444444444444',
                     '22222222-2222-2222-2222-222222222222',
                     '33333333-3333-3333-3333-333333333333', 'storyline', 'active',
                     '55555555-5555-5555-5555-555555555555', '{}'),
                    ('66666666-6666-6666-6666-666666666666',
                     '22222222-2222-2222-2222-222222222222',
                     '33333333-3333-3333-3333-333333333333', 'timeline', 'active',
                     '77777777-7777-7777-7777-777777777777', '{}');
                INSERT INTO characters.storylines
                    (continuity_id, identity_id, persona_id, mode, name, revision)
                VALUES ('44444444-4444-4444-4444-444444444444',
                        '22222222-2222-2222-2222-222222222222',
                        '33333333-3333-3333-3333-333333333333',
                        'storyline', 'Story', 1);
                INSERT INTO characters.timelines
                    (continuity_id, identity_id, persona_id, mode, name,
                     calendar_timezone, revision)
                VALUES ('66666666-6666-6666-6666-666666666666',
                        '22222222-2222-2222-2222-222222222222',
                        '33333333-3333-3333-3333-333333333333',
                        'timeline', 'Timeline', 'UTC', 1);
                INSERT INTO characters.conversations
                    (id, continuity_id, identity_id, persona_id, mode,
                     generation_settings, selected_leaf_id)
                VALUES
                    ('88888888-8888-8888-8888-888888888888',
                     '44444444-4444-4444-4444-444444444444',
                     '22222222-2222-2222-2222-222222222222',
                     '33333333-3333-3333-3333-333333333333', 'storyline', '{}', NULL),
                    ('99999999-9999-9999-9999-999999999999',
                     '66666666-6666-6666-6666-666666666666',
                     '22222222-2222-2222-2222-222222222222',
                     '33333333-3333-3333-3333-333333333333', 'timeline', '{}', NULL);
                INSERT INTO characters.scenes
                    (id, continuity_id, identity_id, persona_id, conversation_id,
                     mode, position, title, setup, response_style, setup_locked)
                VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                        '44444444-4444-4444-4444-444444444444',
                        '22222222-2222-2222-2222-222222222222',
                        '33333333-3333-3333-3333-333333333333',
                        '88888888-8888-8888-8888-888888888888',
                        'storyline', 1, 'Opening', 'At the station', '{}', true);
                INSERT INTO characters.timeline_days
                    (id, continuity_id, identity_id, persona_id, conversation_id,
                     mode, position, local_date, boundary_timezone, opens_at,
                     closes_at, closed_at, settled_selected_leaf_id)
                VALUES ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                        '66666666-6666-6666-6666-666666666666',
                        '22222222-2222-2222-2222-222222222222',
                        '33333333-3333-3333-3333-333333333333',
                        '99999999-9999-9999-9999-999999999999',
                        'timeline', 1, DATE '2026-11-04', 'UTC',
                        TIMESTAMPTZ '2026-11-04 00:00:00+00',
                        TIMESTAMPTZ '2026-11-05 00:00:00+00', NULL, NULL);
                INSERT INTO characters.messages
                    (id, conversation_id, continuity_id, role, content,
                     parent_id, response_provenance, created_at)
                VALUES
                    ('cccccccc-cccc-cccc-cccc-cccccccccccc',
                     '88888888-8888-8888-8888-888888888888',
                     '44444444-4444-4444-4444-444444444444', 'user',
                     'Story input', NULL, NULL, CURRENT_TIMESTAMP),
                    ('dddddddd-dddd-dddd-dddd-dddddddddddd',
                     '99999999-9999-9999-9999-999999999999',
                     '66666666-6666-6666-6666-666666666666', 'user',
                     'Timeline input', NULL, NULL, CURRENT_TIMESTAMP);
                UPDATE characters.conversations
                SET selected_leaf_id = CASE id
                    WHEN '88888888-8888-8888-8888-888888888888'
                    THEN 'cccccccc-cccc-cccc-cccc-cccccccccccc'::uuid
                    ELSE 'dddddddd-dddd-dddd-dddd-dddddddddddd'::uuid END;
                """))


def _assert_normalized_entries(engine: Engine) -> None:
    """Assert exact Entry backfill and detail-only subtype shapes.

    Args:
        engine:
            Disposable PostgreSQL engine at the new head.
    """

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id::text, mode, position, conversation_id::text "
                "FROM characters.continuity_entries ORDER BY mode"
            )
        ).all()
        assert rows == [
            (
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "storyline",
                1,
                "88888888-8888-8888-8888-888888888888",
            ),
            (
                "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "timeline",
                1,
                "99999999-9999-9999-9999-999999999999",
            ),
        ]
        assert connection.scalar(text("SELECT count(*) FROM characters.messages")) == 2

    shared = {
        "continuity_id",
        "identity_id",
        "persona_id",
        "conversation_id",
        "mode",
        "position",
    }
    inspector = inspect(engine)
    for table in ("scenes", "timeline_days"):
        assert shared.isdisjoint(
            column["name"]
            for column in inspector.get_columns(table, schema="characters")
        )


def _assert_denormalized_entries(engine: Engine) -> None:
    """Assert downgrade restores exact shared subtype facts.

    Args:
        engine:
            Disposable PostgreSQL engine at the preceding head.
    """

    assert "continuity_entries" not in inspect(engine).get_table_names(
        schema="characters"
    )
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT mode, position, conversation_id::text FROM characters.scenes")
        ).one() == (
            "storyline",
            1,
            "88888888-8888-8888-8888-888888888888",
        )
        assert connection.execute(
            text(
                "SELECT mode, position, conversation_id::text, local_date::text "
                "FROM characters.timeline_days"
            )
        ).one() == (
            "timeline",
            1,
            "99999999-9999-9999-9999-999999999999",
            "2026-11-04",
        )
