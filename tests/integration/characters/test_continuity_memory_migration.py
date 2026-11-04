"""PostgreSQL migration coverage for unified Continuity memory provenance."""

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from tests.integration.characters.test_continuity_entry_postgres import (
    _insert_prior_head_entries,
)
from tests.integration.characters.test_continuity_postgres import _configuration

pytestmark = pytest.mark.characters_postgres
PRIOR_HEAD = "f3a7c9e1b2d4"


def test_memory_migration_preserves_storyline_and_timeline_entry_provenance(
    characters_postgres_engine: Engine,
) -> None:
    """Normalize representative Scene and Day memory rows through a round trip.

    Args:
        characters_postgres_engine:
            Explicit disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    configuration = _configuration(engine)
    command.upgrade(configuration, "d6e8f1a2b3c4")
    _insert_prior_head_entries(engine)
    command.upgrade(configuration, PRIOR_HEAD)
    _insert_prior_memory(engine)

    command.upgrade(configuration, "head")
    command.check(configuration)
    _assert_unified_memory(engine)

    command.downgrade(configuration, PRIOR_HEAD)
    _assert_legacy_memory(engine)
    command.upgrade(configuration, "head")
    command.check(configuration)
    _assert_unified_memory(engine)


def _insert_prior_memory(engine: Engine) -> None:
    """Insert one Storyline and one Timeline lineage at the Slice 3 head.

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
                 '{}', CURRENT_TIMESTAMP),
                ('ffffffff-ffff-ffff-ffff-ffffffffffff',
                 '99999999-9999-9999-9999-999999999999',
                 '66666666-6666-6666-6666-666666666666', 'persona',
                 'Timeline response', 'dddddddd-dddd-dddd-dddd-dddddddddddd',
                 '{}', CURRENT_TIMESTAMP);
            UPDATE characters.conversations
            SET selected_leaf_id = CASE id
                WHEN '88888888-8888-8888-8888-888888888888'
                THEN 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'::uuid
                ELSE 'ffffffff-ffff-ffff-ffff-ffffffffffff'::uuid END;

            INSERT INTO characters.storyline_memories
                (id, continuity_id, identity_id, persona_id, mode,
                 current_revision_id, subject_key)
            VALUES
                ('10000000-0000-0000-0000-000000000001',
                 '44444444-4444-4444-4444-444444444444',
                 '22222222-2222-2222-2222-222222222222',
                 '33333333-3333-3333-3333-333333333333', 'storyline', NULL,
                 'story fact'),
                ('10000000-0000-0000-0000-000000000002',
                 '66666666-6666-6666-6666-666666666666',
                 '22222222-2222-2222-2222-222222222222',
                 '33333333-3333-3333-3333-333333333333', 'timeline', NULL,
                 'timeline fact');

            INSERT INTO characters.memory_extraction_effects
                (id, continuity_id, identity_id, persona_id, conversation_id,
                 mode, scene_id, day_id, source_persona_message_id, state,
                 selection_id, provenance, created_at, completed_at)
            VALUES
                ('20000000-0000-0000-0000-000000000001',
                 '44444444-4444-4444-4444-444444444444',
                 '22222222-2222-2222-2222-222222222222',
                 '33333333-3333-3333-3333-333333333333',
                 '88888888-8888-8888-8888-888888888888', 'storyline',
                 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', NULL,
                 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee', 'reserved',
                 NULL, NULL, CURRENT_TIMESTAMP, NULL),
                ('20000000-0000-0000-0000-000000000002',
                 '66666666-6666-6666-6666-666666666666',
                 '22222222-2222-2222-2222-222222222222',
                 '33333333-3333-3333-3333-333333333333',
                 '99999999-9999-9999-9999-999999999999', 'timeline', NULL,
                 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                 'ffffffff-ffff-ffff-ffff-ffffffffffff', 'reserved',
                 NULL, NULL, CURRENT_TIMESTAMP, NULL);

            INSERT INTO characters.memory_evidence
                (id, memory_id, continuity_id, identity_id, persona_id,
                 conversation_id, mode, purpose, scene_id, day_id,
                 user_message_id, source_persona_message_id, persona_checkpoint,
                 occurrence_scene_id, occurrence_day_id, occurrence_position,
                 learned_scene_id, learned_day_id, learned_position, extraction,
                 created_at)
            VALUES
                ('30000000-0000-0000-0000-000000000001',
                 '10000000-0000-0000-0000-000000000001',
                 '44444444-4444-4444-4444-444444444444',
                 '22222222-2222-2222-2222-222222222222',
                 '33333333-3333-3333-3333-333333333333',
                 '88888888-8888-8888-8888-888888888888', 'storyline', 'support',
                 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', NULL,
                 'cccccccc-cccc-cccc-cccc-cccccccccccc',
                 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee', 2,
                 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', NULL, 1,
                 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', NULL, 1, '{}',
                 CURRENT_TIMESTAMP),
                ('30000000-0000-0000-0000-000000000002',
                 '10000000-0000-0000-0000-000000000002',
                 '66666666-6666-6666-6666-666666666666',
                 '22222222-2222-2222-2222-222222222222',
                 '33333333-3333-3333-3333-333333333333',
                 '99999999-9999-9999-9999-999999999999', 'timeline', 'support',
                 NULL, 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                 'dddddddd-dddd-dddd-dddd-dddddddddddd',
                 'ffffffff-ffff-ffff-ffff-ffffffffffff', 2,
                 NULL, 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 1,
                 NULL, 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 1, '{}',
                 CURRENT_TIMESTAMP);

            INSERT INTO characters.memory_revisions
                (id, memory_id, continuity_id, revision, predecessor_id, subject,
                 content, state, authorship, kind, source_evidence_id, created_at)
            VALUES
                ('40000000-0000-0000-0000-000000000001',
                 '10000000-0000-0000-0000-000000000001',
                 '44444444-4444-4444-4444-444444444444', 1, NULL, 'story fact',
                 'Story fact content', 'active', 'extracted', 'extraction',
                 '30000000-0000-0000-0000-000000000001', CURRENT_TIMESTAMP),
                ('40000000-0000-0000-0000-000000000002',
                 '10000000-0000-0000-0000-000000000002',
                 '66666666-6666-6666-6666-666666666666', 1, NULL, 'timeline fact',
                 'Timeline fact content', 'active', 'extracted', 'extraction',
                 '30000000-0000-0000-0000-000000000002', CURRENT_TIMESTAMP);
            UPDATE characters.storyline_memories
            SET current_revision_id = CASE id
                WHEN '10000000-0000-0000-0000-000000000001'
                THEN '40000000-0000-0000-0000-000000000001'::uuid
                ELSE '40000000-0000-0000-0000-000000000002'::uuid END;
            """))


def _assert_unified_memory(engine: Engine) -> None:
    """Assert unified table names, columns, and exact Entry mappings.

    Args:
        engine:
            Disposable PostgreSQL engine at the new head.
    """

    inspector = inspect(engine)
    assert "continuity_memories" in inspector.get_table_names(schema="characters")
    assert "storyline_memories" not in inspector.get_table_names(schema="characters")
    evidence_columns = {
        column["name"]
        for column in inspector.get_columns("memory_evidence", schema="characters")
    }
    assert {"entry_id", "occurrence_entry_id", "learned_entry_id"} <= evidence_columns
    assert (
        not {
            "scene_id",
            "day_id",
            "occurrence_scene_id",
            "occurrence_day_id",
            "learned_scene_id",
            "learned_day_id",
        }
        & evidence_columns
    )
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT mode, entry_id::text, occurrence_entry_id::text, "
                "learned_entry_id::text FROM characters.memory_evidence ORDER BY mode"
            )
        ).all()
        effects = connection.execute(
            text(
                "SELECT mode, entry_id::text FROM characters.memory_extraction_effects "
                "ORDER BY mode"
            )
        ).all()
    assert rows == [
        ("storyline",) + ("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",) * 3,
        ("timeline",) + ("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",) * 3,
    ]
    assert effects == [
        ("storyline", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ("timeline", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    ]


def _assert_legacy_memory(engine: Engine) -> None:
    """Assert downgrade restores the prior paired provenance without data loss.

    Args:
        engine:
            Disposable PostgreSQL engine at the prior head.
    """

    inspector = inspect(engine)
    assert "storyline_memories" in inspector.get_table_names(schema="characters")
    assert "continuity_memories" not in inspector.get_table_names(schema="characters")
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT mode, scene_id::text, day_id::text "
                "FROM characters.memory_evidence ORDER BY mode"
            )
        ).all()
    assert rows == [
        ("storyline", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", None),
        ("timeline", None, "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    ]
