"""Disposable PostgreSQL turn constraints, serialization, and migration acceptance."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, local

import pytest
from alembic import command
from sqlalchemy import event, inspect, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    AttemptConflictError,
    GenerationAttempt,
    IncompleteTurnError,
    Message,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.models import (
    GenerationAttemptModel,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbConversationRepository,
)
from tests.characters_support import FakeResponse, service, start
from tests.integration.characters.test_continuity_postgres import (
    _chat_snapshot,
    _configuration,
)

pytestmark = pytest.mark.characters_postgres
PRIOR_HEAD = "83a2c09d7f41"


def test_turn_migration_round_trips_and_preserves_populated_chat(
    characters_postgres_engine: Engine,
) -> None:
    """Verify fresh/prior upgrades, reversal, ownership, constraints, and Chat isolation.

    Args:
        characters_postgres_engine:
            Explicit disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    command.upgrade(_configuration(engine, "chat"), "head")
    from sqlalchemy import text

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO chat.conversations (id,title,requested_generation_configuration,created_at,updated_at) VALUES ('11111111-1111-1111-1111-111111111111','Preserve Chat','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
    before = _chat_snapshot(engine)
    configuration = _configuration(engine)
    command.upgrade(configuration, PRIOR_HEAD)
    factory = sessionmaker(bind=engine)
    command.upgrade(configuration, "head")
    existing = start(factory)
    command.check(configuration)
    app = service(factory, FakeResponse())
    attempt = app.send(existing, SubmittedInput(content="Preserve profiles"))
    # The partial index and ownership guards also protect direct persistence writes.
    with factory() as session:
        row = session.get(GenerationAttemptModel, attempt.id)
        assert row is not None
        values = {
            column.name: getattr(row, column.name)
            for column in row.__table__.columns
            if column.name != "id"
        }
    with (
        pytest.raises(IntegrityError, match="uq_open_conversation_attempt"),
        factory() as session,
        session.begin(),
    ):
        session.add(GenerationAttemptModel(**values))
        session.flush()
    foreign = start(factory)
    with (
        pytest.raises(IntegrityError, match="fk_attempt_user"),
        factory() as session,
        session.begin(),
    ):
        session.execute(
            update(GenerationAttemptModel)
            .where(GenerationAttemptModel.id == attempt.id)
            .values(
                conversation_id=foreign.conversation_id,
                continuity_id=foreign.continuity_id,
            )
        )
    list(app.stream(existing, attempt.id))
    message_columns = {
        column["name"]
        for column in inspect(engine).get_columns("messages", schema="characters")
    }
    assert "parent_id" in message_columns
    assert "response_provenance" in message_columns
    assert "sequence" not in message_columns
    assert "reply_to" not in message_columns
    for table in ["messages", "generation_attempts"]:
        assert all(
            fk["referred_schema"] == "characters"
            for fk in inspect(engine).get_foreign_keys(table, schema="characters")
        )
    assert _chat_snapshot(engine) == before
    command.downgrade(configuration, PRIOR_HEAD)
    assert "messages" not in inspect(engine).get_table_names(schema="characters")
    command.upgrade(configuration, "head")
    command.check(configuration)
    assert app.history(existing).messages == ()
    assert _chat_snapshot(engine) == before
    # Also prove a fresh baseline upgrade independently of surviving profile rows.
    command.downgrade(configuration, "base")
    command.upgrade(configuration, "head")
    command.check(configuration)
    assert _chat_snapshot(engine) == before


@pytest.mark.parametrize("action", ["send", "claim", "complete", "continue"])
def test_competing_turn_actions_have_exactly_one_winner(
    characters_postgres_engine: Engine, action: str
) -> None:
    """Serialize competing writes under continuity locking.

    Args:
        characters_postgres_engine:
            Explicit disposable PostgreSQL database.
        action:
            Competing operation to exercise.
    """

    factory = _factory(characters_postgres_engine)
    scope = start(factory)
    app = service(factory, FakeResponse())
    repository = DbConversationRepository(factory)
    operation: Callable[[], object]
    if action == "send":
        operation = lambda: app.send(scope, SubmittedInput(content="Competing input"))
    else:
        attempt = app.send(scope, SubmittedInput(content="Input"))
        if action == "claim":
            operation = lambda: repository.claim(scope, attempt.id)
        elif action == "complete":
            repository.claim(scope, attempt.id)
            repository.append(scope, attempt.id, "Answer")
            operation = lambda: repository.complete(scope, attempt.id)
        else:
            repository.stop(scope, attempt.id, "failed")
            operation = lambda: app.continue_incomplete_turn(scope)
    outcomes = _race(operation, operation)
    assert sum(isinstance(item, (GenerationAttempt, Message)) for item in outcomes) == 1
    assert (
        sum(
            isinstance(item, (AttemptConflictError, IncompleteTurnError))
            for item in outcomes
        )
        == 1
    )
    saved = app.history(scope)
    assert len(saved.messages) == (2 if action == "complete" else 1)
    assert sum(a.status in {"pending", "streaming"} for a in saved.attempts) <= 1


@pytest.mark.parametrize("winner", ["archive", "complete"])
def test_archive_completion_row_lock_order_determines_commit(
    characters_postgres_engine: Engine, winner: str
) -> None:
    """Force both race orders and prevent a persona commit after archive.

    Args:
        characters_postgres_engine:
            Explicit disposable PostgreSQL database.
        winner:
            Operation acquiring the continuity row lock first.
    """

    engine = characters_postgres_engine
    factory = _factory(engine)
    scope = start(factory)
    repository = DbConversationRepository(factory)
    app = service(factory, FakeResponse())
    attempt = app.send(scope, SubmittedInput(content="Input"))
    repository.claim(scope, attempt.id)
    repository.append(scope, attempt.id, "Answer")
    locked, issued, release = Event(), Event(), Event()
    worker = local()

    def before(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        """Observe the competing lock query before allowing the winner to commit.

        Args:
            connection:
                Current connection.
            cursor:
                DBAPI cursor.
            statement:
                SQL being executed.
            parameters:
                Bound parameters.
            context:
                Execution context.
            executemany:
                Whether this is a batch.
        """

        if (
            getattr(worker, "role", None) != winner
            and "characters.continuities" in statement.lower()
            and "FOR UPDATE" in statement
        ):
            issued.set()

    def after(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        """Hold the winning continuity lock until the competitor requests it.

        Args:
            connection:
                Current connection.
            cursor:
                DBAPI cursor.
            statement:
                SQL just executed.
            parameters:
                Bound parameters.
            context:
                Execution context.
            executemany:
                Whether this is a batch.
        """

        if (
            getattr(worker, "role", None) == winner
            and "characters.continuities" in statement.lower()
            and "FOR UPDATE" in statement
            and not locked.is_set()
        ):
            locked.set()
            assert release.wait(timeout=10)

    def run(role: str) -> object:
        """Execute archive or completion under an identifiable worker role.

        Args:
            role:
                Operation to perform.

        Returns:
            Snapshot or expected archived failure.
        """

        worker.role = role
        try:
            if role == "complete":
                return repository.complete(scope, attempt.id)
            return DbContinuityRepository(factory).archive(
                scope.identity_id, scope.persona_id, scope.continuity_id
            )
        except ArchivedContinuityError as error:
            return error

    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(run, winner)
            try:
                assert locked.wait(timeout=10)
                second = executor.submit(
                    run, "complete" if winner == "archive" else "archive"
                )
                assert issued.wait(timeout=10)
            finally:
                release.set()
            outcomes = [first.result(timeout=10), second.result(timeout=10)]
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)
    if winner == "archive":
        assert isinstance(outcomes[1], ArchivedContinuityError)
        assert len(app.history(scope).messages) == 1
    else:
        assert isinstance(outcomes[0], Message)
        assert len(app.history(scope).messages) == 2
    with pytest.raises(ArchivedContinuityError):
        repository.append(scope, attempt.id, "Late output")


def _factory(engine: Engine) -> sessionmaker[Session]:
    """Apply the Characters head and bind disposable sessions.

    Args:
        engine:
            Disposable PostgreSQL engine.

    Returns:
        Fresh session factory.
    """

    command.upgrade(_configuration(engine), "head")
    return sessionmaker(bind=engine)


def _race(first: Callable[[], object], second: Callable[[], object]) -> list[object]:
    """Start competing operations together and retain expected domain conflicts.

    Args:
        first:
            First operation.
        second:
            Competing operation.

    Returns:
        Successful snapshots or expected conflict errors.
    """

    barrier = Barrier(2)

    def run(operation: Callable[[], object]) -> object:
        """Synchronize a real repository mutation with its competitor.

        Args:
            operation:
                Mutation to execute.

        Returns:
            Snapshot or expected conflict.
        """

        barrier.wait(timeout=10)
        try:
            return operation()
        except (AttemptConflictError, IncompleteTurnError) as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        return list(executor.map(run, [first, second]))


def test_send_racing_completion_keeps_a_single_unmatched_tail(
    characters_postgres_engine: Engine,
) -> None:
    """Accept new input only after completion has committed the previous response.

    Args:
        characters_postgres_engine:
            Explicit disposable PostgreSQL database.
    """

    factory = _factory(characters_postgres_engine)
    scope = start(factory)
    app = service(factory, FakeResponse())
    repository = DbConversationRepository(factory)
    pending = app.send(scope, SubmittedInput(content="First"))
    repository.claim(scope, pending.id)
    repository.append(scope, pending.id, "Answer")
    completed, sent = _race(
        lambda: repository.complete(scope, pending.id),
        lambda: app.send(scope, SubmittedInput(content="Second")),
    )
    assert isinstance(completed, Message)
    saved = app.history(scope)
    assert [m.content for m in saved.messages[:2]] == ["First", "Answer"]
    if isinstance(sent, GenerationAttempt):
        assert len(saved.messages) == 3
        assert saved.messages[-1].id == sent.user_message_id
        assert sum(a.status == "pending" for a in saved.attempts) == 1
        list(app.stream(scope, sent.id))
        assert [m.sequence for m in app.history(scope).messages] == [1, 2, 3, 4]
    else:
        assert isinstance(sent, AttemptConflictError)
        assert len(saved.messages) == 2
        assert all(a.status == "completed" for a in saved.attempts)
