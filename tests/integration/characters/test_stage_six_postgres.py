"""PostgreSQL and area-isolation proof of the complete Stage 6 milestone."""

import pytest
from alembic import command
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine, ExecutionContext
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import visitors
from sqlalchemy.sql.schema import Table

from tests.integration.characters.test_continuity_postgres import (
    _chat_snapshot,
    _configuration,
)
from tests.integration.characters.test_stage_six_acceptance import (
    prove_stage_six_milestone,
)

pytestmark = pytest.mark.characters_postgres


def test_complete_stage_six_chain_and_journey_preserve_populated_chat(
    characters_postgres_engine: Engine,
) -> None:
    """Run every migration and the acceptance journey beside private Chat data.

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
                "'Stage 6 private Chat','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
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
    inspector = inspect(engine)
    expected_stage_six_tables = {
        "storylines",
        "scenes",
        "storyline_memories",
        "memory_revisions",
        "memory_evidence",
        "memory_extraction_effects",
        "memory_conflicts",
    }
    assert expected_stage_six_tables <= set(
        inspector.get_table_names(schema="characters")
    )
    for table in expected_stage_six_tables:
        assert all(
            foreign_key["referred_schema"] == "characters"
            for foreign_key in inspector.get_foreign_keys(table, schema="characters")
        )

    queried_tables: set[str] = set()

    def verify_query_scope(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: ExecutionContext,
        executemany: bool,
    ) -> None:
        """Require every acceptance-query table to belong to Characters.

        Args:
            connection:
                Active connection.
            cursor:
                DBAPI cursor.
            statement:
                Rendered repository statement.
            parameters:
                Bound values.
            context:
                Compilation context containing the SQL expression.
            executemany:
                Whether multiple rows are being written.
        """

        assert context.compiled is not None, statement
        for node in visitors.iterate(context.compiled.statement):
            if isinstance(node, Table):
                assert node.schema == "characters", statement
                queried_tables.add(node.name)

    event.listen(engine, "before_cursor_execute", verify_query_scope)
    try:
        prove_stage_six_milestone(sessionmaker(bind=engine, autoflush=False))
    finally:
        event.remove(engine, "before_cursor_execute", verify_query_scope)

    assert expected_stage_six_tables <= queried_tables
    assert _chat_snapshot(engine) == before
