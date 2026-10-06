"""PostgreSQL acceptance for the in-place Characters graph migration."""

import json

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from tests.integration.characters.test_continuity_postgres import (
    _chat_snapshot,
    _configuration,
)

pytestmark = pytest.mark.characters_postgres
PRIOR_HEAD = "a6148d2e37c9"


def test_populated_linear_history_becomes_one_exact_selected_graph(
    characters_postgres_engine: Engine,
) -> None:
    """Preserve records while backfilling parents, selection, and provenance.

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
    generation = json.dumps(
        {
            "model": {
                "provider": "fake",
                "model": "first",
                "context_tokens": 8192,
                "output_tokens": 128,
                "capabilities": ["response"],
                "parameters": [],
            },
            "configuration": {"max_output_tokens": 128},
            "capability": "response",
            "input_tokens": 8064,
        }
    )
    summary_generation = json.dumps(
        {
            "model": {
                "provider": "fake",
                "model": "summary",
                "context_tokens": 8192,
                "output_tokens": 128,
                "capabilities": ["summary"],
                "parameters": [],
            },
            "configuration": {"max_output_tokens": 128},
            "capability": "summary",
            "input_tokens": 8064,
        }
    )
    with engine.begin() as connection:
        connection.execute(text("""
                INSERT INTO characters.identities
                    (id,name,revision,is_frozen,default_key)
                VALUES ('20000000-0000-0000-0000-000000000001','You',1,true,'you');
                INSERT INTO characters.personas
                    (id,name,definition,revision,is_frozen)
                VALUES ('30000000-0000-0000-0000-000000000001','Guide','Helpful',1,true);
                INSERT INTO characters.continuities
                    (id,identity_id,persona_id,mode,lifecycle,request_id,confirmed_request)
                VALUES (
                    '40000000-0000-0000-0000-000000000001',
                    '20000000-0000-0000-0000-000000000001',
                    '30000000-0000-0000-0000-000000000001',
                    'ongoing','active','50000000-0000-0000-0000-000000000001','{}'
                );
                INSERT INTO characters.conversations
                    (id,continuity_id,identity_id,persona_id,generation_settings)
                VALUES (
                    '60000000-0000-0000-0000-000000000001',
                    '40000000-0000-0000-0000-000000000001',
                    '20000000-0000-0000-0000-000000000001',
                    '30000000-0000-0000-0000-000000000001',NULL
                );
                INSERT INTO characters.starting_relationships
                    (continuity_id,identity_id,persona_id,snapshot)
                VALUES (
                    '40000000-0000-0000-0000-000000000001',
                    '20000000-0000-0000-0000-000000000001',
                    '30000000-0000-0000-0000-000000000001','{}'
                );
                INSERT INTO characters.messages
                    (id,conversation_id,continuity_id,sequence,role,content,reply_to,created_at)
                VALUES
                    ('70000000-0000-0000-0000-000000000001','60000000-0000-0000-0000-000000000001','40000000-0000-0000-0000-000000000001',1,'user','Hello',NULL,'2026-01-01T00:00:00Z'),
                    ('70000000-0000-0000-0000-000000000002','60000000-0000-0000-0000-000000000001','40000000-0000-0000-0000-000000000001',2,'persona','Hi','70000000-0000-0000-0000-000000000001','2026-01-01T00:00:01Z');
                """))
        connection.execute(
            text("""
                INSERT INTO characters.generation_attempts
                    (id,conversation_id,continuity_id,user_message_id,persona_message_id,
                     submitted_input,generation,status,incomplete_output,created_at,updated_at,finished_at)
                VALUES (
                    '80000000-0000-0000-0000-000000000001',
                    '60000000-0000-0000-0000-000000000001',
                    '40000000-0000-0000-0000-000000000001',
                    '70000000-0000-0000-0000-000000000001',
                    '70000000-0000-0000-0000-000000000002',
                    'Hello',CAST(:generation AS json),'completed','Hi',
                    '2026-01-01T00:00:00Z','2026-01-01T00:00:01Z','2026-01-01T00:00:01Z'
                )
                """),
            {"generation": generation},
        )
        connection.execute(
            text("""
                INSERT INTO characters.summary_revisions
                    (id,conversation_id,continuity_id,revision,predecessor_id,
                     checkpoint_message_id,checkpoint_sequence,content,generation,is_active,created_at)
                VALUES (
                    '90000000-0000-0000-0000-000000000001',
                    '60000000-0000-0000-0000-000000000001',
                    '40000000-0000-0000-0000-000000000001',1,NULL,
                    '70000000-0000-0000-0000-000000000002',2,'Greeting',
                    CAST(:generation AS json),true,'2026-01-01T00:00:02Z'
                )
                """),
            {"generation": summary_generation},
        )

    command.upgrade(configuration, "head")
    command.check(configuration)
    with engine.connect() as connection:
        messages = (
            connection.execute(
                text(
                    "SELECT id,parent_id,response_provenance FROM characters.messages "
                    "ORDER BY created_at"
                )
            )
            .mappings()
            .all()
        )
        selected = connection.scalar(
            text("SELECT selected_leaf_id FROM characters.conversations")
        )
        attempt_count = connection.scalar(
            text("SELECT count(*) FROM characters.generation_attempts")
        )
        selection_guard = connection.scalar(
            text("SELECT selection_guard_id FROM characters.generation_attempts")
        )
        summary = (
            connection.execute(
                text(
                    "SELECT id,checkpoint_message_id FROM characters.summary_revisions"
                )
            )
            .mappings()
            .one()
        )
    assert messages[0]["parent_id"] is None
    assert str(messages[1]["parent_id"]) == str(messages[0]["id"])
    assert messages[1]["response_provenance"]["attempt_id"] == (
        "80000000-0000-0000-0000-000000000001"
    )
    assert str(selected) == "70000000-0000-0000-0000-000000000002"
    assert attempt_count == 1
    assert str(selection_guard) == "70000000-0000-0000-0000-000000000001"
    assert str(summary["id"]) == "90000000-0000-0000-0000-000000000001"
    assert _chat_snapshot(engine) == before
    columns = {
        column["name"]
        for column in inspect(engine).get_columns(
            "summary_revisions", schema="characters"
        )
    }
    assert "is_active" not in columns and "checkpoint_sequence" not in columns

    command.downgrade(configuration, PRIOR_HEAD)
    with engine.connect() as connection:
        restored = (
            connection.execute(
                text(
                    "SELECT id,sequence,reply_to FROM characters.messages ORDER BY sequence"
                )
            )
            .mappings()
            .all()
        )
    assert [row["sequence"] for row in restored] == [1, 2]
    assert str(restored[1]["reply_to"]) == str(restored[0]["id"])
    assert _chat_snapshot(engine) == before
