"""PostgreSQL proof of the complete Stage 5 milestone."""

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
from tests.integration.characters.test_stage_five_acceptance import (
    prove_stage_five_milestone,
)

pytestmark = pytest.mark.characters_postgres


def test_complete_migration_chain_and_milestone_preserve_populated_chat(
    characters_postgres_engine: Engine,
) -> None:
    """Run the isolated migration chain and Stage 5 acceptance scenario.

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
                "'Private Chat history','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO chat.messages (id,conversation_id,role,content,created_at) "
                "VALUES ('22222222-2222-2222-2222-222222222222',"
                "'11111111-1111-1111-1111-111111111111','user',"
                "'Private Chat input',CURRENT_TIMESTAMP)"
            )
        )
    before = _chat_snapshot(engine)
    configuration = _configuration(engine)
    command.upgrade(configuration, "head")
    command.check(configuration)
    assert _chat_snapshot(engine) == before

    inspector = inspect(engine)
    with engine.connect() as connection:
        assert set(
            connection.scalars(
                text("SELECT version_num FROM characters.alembic_version")
            )
        ) == {"c8d2f41a9b70"}
    queried_tables: set[str] = set()

    def verify_query_scope(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: ExecutionContext,
        executemany: bool,
    ) -> None:
        """Require every runtime table reference to belong to Characters.

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
        prove_stage_five_milestone(sessionmaker(bind=engine))
    finally:
        event.remove(engine, "before_cursor_execute", verify_query_scope)

    assert queried_tables == set(inspector.get_table_names(schema="characters")) - {
        "alembic_version"
    }
    assert _chat_snapshot(engine) == before
