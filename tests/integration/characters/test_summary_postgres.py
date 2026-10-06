"""PostgreSQL migration and concurrency acceptance for rolling summaries."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from chat_buddy.characters.domain import (
    SubmittedInput,
    SummaryConflictError,
    SummaryRevision,
)
from chat_buddy.characters.infrastructure.db.repositories import DbSummaryRepository
from tests.characters_support import FakeResponse, start
from tests.integration.characters.test_continuity_postgres import (
    _chat_snapshot,
    _configuration,
)
from tests.integration.characters.test_ongoing_summary_context import (
    FakeSummary,
    _service,
)

pytestmark = pytest.mark.characters_postgres
PRIOR_HEAD = "f71d92ab0c55"


def test_summary_migration_and_concurrent_replacement_preserve_chat(
    characters_postgres_engine: Engine,
) -> None:
    """Verify migration reversal, ownership, and one stale-writer winner.

    Args:
        characters_postgres_engine:
            Explicit disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    command.upgrade(_configuration(engine, "chat"), "head")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO chat.conversations (id,title,requested_generation_configuration,created_at,updated_at) VALUES ('11111111-1111-1111-1111-111111111111','Preserve Chat','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
    before = _chat_snapshot(engine)
    configuration = _configuration(engine)
    command.upgrade(configuration, PRIOR_HEAD)
    command.upgrade(configuration, "head")
    command.check(configuration)
    factory = sessionmaker(bind=engine)
    scope = start(factory)
    app = _service(factory, FakeResponse(), FakeSummary())
    for content in ("First", "Second", "Third"):
        attempt = app.send(scope, SubmittedInput(content=content))
        list(app.stream(scope, attempt.id))
    pending = app.send(scope, SubmittedInput(content="Fourth"))
    repository = DbSummaryRepository(factory)
    active = repository.get_active(scope)
    assert active is not None and active.revision == 2
    checkpoint = app.history(scope).messages[5]

    def replace(label: str) -> SummaryRevision:
        """Attempt one successor from the same observed active revision.

        Args:
            label:
                Distinct generated content.

        Returns:
            Winning persisted successor.
        """

        successor = active.model_copy(
            update={
                "id": uuid4(),
                "revision": active.revision + 1,
                "predecessor_id": active.id,
                "checkpoint_message_id": checkpoint.id,
                "checkpoint_sequence": checkpoint.sequence,
                "content": label,
            }
        )
        return repository.replace(
            successor, active.revision, active.checkpoint_message_id
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [
            future.exception() or future.result()
            for future in (
                executor.submit(replace, "First contender"),
                executor.submit(replace, "Second contender"),
            )
        ]
    assert sum(isinstance(item, SummaryRevision) for item in outcomes) == 1
    assert sum(isinstance(item, SummaryConflictError) for item in outcomes) == 1
    revisions = _all_revisions(engine)
    assert len(revisions) == 3
    assert "is_active" not in revisions[0]
    assert "checkpoint_sequence" not in revisions[0]
    assert repository.get_active(scope) is not None
    foreign_keys = inspect(engine).get_foreign_keys(
        "summary_revisions", schema="characters"
    )
    assert all(item["referred_schema"] == "characters" for item in foreign_keys)
    list(app.stream(scope, pending.id))
    assert _chat_snapshot(engine) == before

    command.downgrade(configuration, PRIOR_HEAD)
    assert "summary_revisions" not in inspect(engine).get_table_names(
        schema="characters"
    )
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM characters.messages"))
    command.upgrade(configuration, "head")
    command.check(configuration)
    assert repository.get_active(scope) is None
    assert _chat_snapshot(engine) == before


def _all_revisions(engine: Engine) -> list[dict[str, object]]:
    """Read branch-addressable summary rows for database verification.

    Args:
        engine:
            Disposable PostgreSQL engine.

    Returns:
        Mapping rows for all persisted summary revisions.
    """

    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text("SELECT * FROM characters.summary_revisions")
            ).mappings()
        ]
