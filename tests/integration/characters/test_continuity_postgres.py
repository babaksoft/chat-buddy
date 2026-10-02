"""Disposable PostgreSQL continuity migration, locking, and race acceptance."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, local
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import event, inspect, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import ContinuityService
from chat_buddy.characters.domain import (
    ActiveContinuityError,
    ConfirmationConflictError,
    Continuity,
    FrozenIdentityError,
    FrozenPersonaError,
    Identity,
    IdentityDetails,
    Persona,
    PersonaCore,
    RelationshipIntent,
    RelationshipSelection,
    StaleIdentityError,
    StalePersonaError,
    StartContinuity,
)
from chat_buddy.characters.infrastructure.db.models import (
    ContinuityModel,
    ConversationModel,
    StartingRelationshipModel,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbIdentityRepository,
    DbPersonaRepository,
)

pytestmark = pytest.mark.characters_postgres
PRIOR_HEAD = "5cb588ac2285"


def test_continuity_migration_and_database_constraints_preserve_chat(
    characters_postgres_engine: Engine,
) -> None:
    """Check fresh/prior upgrades, reversal, metadata parity, and direct constraints.

    Args:
        characters_postgres_engine:
            Disposable PostgreSQL database engine.
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
    command.upgrade(configuration, "head")
    command.check(configuration)
    factory = sessionmaker(bind=engine)
    request = _request(factory)
    service = ContinuityService(DbContinuityRepository(factory))
    original = service.start(request)
    # The partial uniqueness guard must work independently of repository checks.
    with pytest.raises(IntegrityError), factory() as session, session.begin():
        session.add(
            ContinuityModel(
                identity_id=original.identity_id,
                persona_id=original.persona_id,
                mode="ongoing",
                lifecycle="active",
                request_id=uuid4(),
                confirmed_request={},
            )
        )
        session.flush()
    wrong_identity = DbIdentityRepository(factory).create(IdentityDetails(name="Other"))
    child_models: tuple[type[ConversationModel | StartingRelationshipModel], ...] = (
        ConversationModel,
        StartingRelationshipModel,
    )
    for model in child_models:
        with (
            pytest.raises(IntegrityError, match="ownership"),
            factory() as session,
            session.begin(),
        ):
            session.execute(
                update(model)
                .where(model.continuity_id == original.id)
                .values(identity_id=wrong_identity.id)
            )
    archived = service.archive(original.identity_id, original.persona_id, original.id)
    # Archival releases only the active slot, retaining original children.
    second = service.start(request.model_copy(update={"request_id": uuid4()}))
    assert (
        service.resume(archived.identity_id, archived.persona_id, archived.id)
        == archived
    )
    assert second.id != original.id
    for table in ["continuities", "conversations", "starting_relationships"]:
        assert all(
            fk["referred_schema"] == "characters"
            for fk in inspect(engine).get_foreign_keys(table, schema="characters")
        )
    assert _chat_snapshot(engine) == before
    command.downgrade(configuration, PRIOR_HEAD)
    assert sorted(inspect(engine).get_table_names(schema="characters")) == [
        "alembic_version",
        "identities",
        "personas",
    ]
    assert DbIdentityRepository(factory).get(original.identity_id).is_frozen
    assert DbPersonaRepository(factory).get(original.persona_id).is_frozen
    command.upgrade(configuration, "head")
    command.check(configuration)
    assert DbContinuityRepository(factory).list() == []
    assert _chat_snapshot(engine) == before


@pytest.mark.parametrize("identical", [False, True])
def test_two_starts_serialize_with_one_active_pair(
    characters_postgres_engine: Engine, identical: bool
) -> None:
    """Competing starts produce one active record or the same confirmation result.

    Args:
        characters_postgres_engine:
            Disposable PostgreSQL database engine.
        identical:
            Whether both callers submit the same confirmation.
    """

    factory = _factory(characters_postgres_engine)
    request = _request(factory)
    other = request if identical else request.model_copy(update={"request_id": uuid4()})
    service = ContinuityService(DbContinuityRepository(factory))
    outcomes = _race(lambda: service.start(request), lambda: service.start(other))
    winners = [outcome for outcome in outcomes if isinstance(outcome, Continuity)]
    assert len(winners) == (2 if identical else 1)
    if identical:
        assert winners[0] == winners[1]
    else:
        assert (
            sum(isinstance(outcome, ActiveContinuityError) for outcome in outcomes) == 1
        )
    assert DbContinuityRepository(factory).list() == [winners[0]]


@pytest.mark.parametrize("area", ["identity", "persona"])
def test_profile_edit_racing_first_use_preserves_confirmed_semantics(
    characters_postgres_engine: Engine, area: str
) -> None:
    """Either the edit makes start stale or start freezes the competing edit.

    Args:
        characters_postgres_engine:
            Disposable PostgreSQL database engine.
        area:
            Profile type whose edit competes with first use.
    """

    factory = _factory(characters_postgres_engine)
    request = _request(factory)
    service = ContinuityService(DbContinuityRepository(factory))
    identities = DbIdentityRepository(factory)
    personas = DbPersonaRepository(factory)

    def edit() -> Identity | Persona:
        """Submit the competing authored replacement at the reviewed revision.

        Returns:
            The successfully edited profile when it wins the race.
        """

        if area == "identity":
            return identities.replace(
                request.identity_id, IdentityDetails(name="Edited"), 1
            )
        return personas.replace(
            request.persona_id, PersonaCore(name="Edited", definition="Edited"), 1
        )

    outcomes = _race(lambda: service.start(request), edit)
    started, edited = outcomes
    if isinstance(started, Continuity):
        assert isinstance(
            edited, FrozenIdentityError if area == "identity" else FrozenPersonaError
        )
        assert identities.get(request.identity_id).details.name == "You"
        assert personas.get(request.persona_id).core.name == "Guide"
        assert identities.get(request.identity_id).is_frozen
        assert personas.get(request.persona_id).is_frozen
    else:
        assert isinstance(
            started, StaleIdentityError if area == "identity" else StalePersonaError
        )
        assert isinstance(edited, Identity if area == "identity" else Persona)
        assert not identities.get(request.identity_id).is_frozen
        assert not personas.get(request.persona_id).is_frozen
        assert DbContinuityRepository(factory).list() == []


@pytest.mark.parametrize("area", ["identity", "persona"])
@pytest.mark.parametrize("winner", ["start", "edit"])
def test_first_row_lock_determines_edit_start_outcome(
    characters_postgres_engine: Engine, area: str, winner: str
) -> None:
    """Force both lock orders to verify confirmed semantics deterministically.

    Args:
        characters_postgres_engine:
            Disposable PostgreSQL database engine.
        area:
            Profile whose edit races first use.
        winner:
            Operation that acquires its profile lock first.
    """

    engine = characters_postgres_engine
    factory = _factory(engine)
    request = _request(factory)
    service = ContinuityService(DbContinuityRepository(factory))
    identities = DbIdentityRepository(factory)
    personas = DbPersonaRepository(factory)
    locked = Event()
    competitor_issued = Event()
    release = Event()
    worker = local()
    table = "characters.identities" if area == "identity" else "characters.personas"

    def before_execute(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        """Observe the competing SQL before releasing the first row lock.

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
                SQLAlchemy execution context.
            executemany:
                Whether this is a batch execution.
        """

        role = getattr(worker, "role", None)
        sql = statement.lower()
        locks_profile = table in sql and (
            sql.startswith("update ") or "for update" in sql
        )
        if role is not None and role != winner and locks_profile:
            competitor_issued.set()

    def after_execute(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        """Hold the winner's transaction after it actually acquired the row lock.

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
                SQLAlchemy execution context.
            executemany:
                Whether this is a batch execution.
        """

        sql = statement.lower()
        locks_profile = table in sql and (
            sql.startswith("update ") or "for update" in sql
        )
        if (
            getattr(worker, "role", None) == winner
            and locks_profile
            and not locked.is_set()
        ):
            locked.set()
            assert release.wait(timeout=10), "Winner's lock was never released"

    def run(role: str) -> object:
        """Execute a real repository action under an identifiable worker role.

        Args:
            role:
                Start or edit operation.

        Returns:
            Successful domain snapshot or typed concurrency failure.
        """

        worker.role = role
        try:
            if role == "start":
                return service.start(request)
            if area == "identity":
                return identities.replace(
                    request.identity_id, IdentityDetails(name="Edited"), 1
                )
            return personas.replace(
                request.persona_id, PersonaCore(name="Edited", definition="Edited"), 1
            )
        except (
            FrozenIdentityError,
            FrozenPersonaError,
            StaleIdentityError,
            StalePersonaError,
        ) as error:
            return error

    event.listen(engine, "before_cursor_execute", before_execute)
    event.listen(engine, "after_cursor_execute", after_execute)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(run, winner)
            try:
                assert locked.wait(
                    timeout=10
                ), "First operation did not acquire the lock"
                second = executor.submit(run, "edit" if winner == "start" else "start")
                assert competitor_issued.wait(
                    timeout=10
                ), "Competing operation did not issue SQL"
            finally:
                release.set()
            first_result = first.result(timeout=10)
            second_result = second.result(timeout=10)
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", before_execute)
        event.remove(engine, "after_cursor_execute", after_execute)
    if winner == "start":
        assert isinstance(first_result, Continuity)
        assert isinstance(
            second_result,
            FrozenIdentityError if area == "identity" else FrozenPersonaError,
        )
        assert identities.get(request.identity_id).revision == 1
        assert personas.get(request.persona_id).revision == 1
    else:
        assert isinstance(first_result, Identity if area == "identity" else Persona)
        assert isinstance(
            second_result,
            StaleIdentityError if area == "identity" else StalePersonaError,
        )
        assert DbContinuityRepository(factory).list() == []
        assert not identities.get(request.identity_id).is_frozen
        assert not personas.get(request.persona_id).is_frozen


def test_two_identities_first_using_shared_persona_both_start(
    characters_postgres_engine: Engine,
) -> None:
    """Global persona freezing permits distinct-pair starts without deadlock.

    Args:
        characters_postgres_engine:
            Disposable PostgreSQL database engine.
    """

    factory = _factory(characters_postgres_engine)
    request = _request(factory)
    other = DbIdentityRepository(factory).create(IdentityDetails(name="Other"))
    second_request = request.model_copy(
        update={
            "request_id": uuid4(),
            "identity_id": other.id,
            "relationship": RelationshipSelection(
                intent=RelationshipIntent.NATURAL, social="close_friend"
            ),
        }
    )
    service = ContinuityService(DbContinuityRepository(factory))
    first, second = _race(
        lambda: service.start(request), lambda: service.start(second_request)
    )
    assert isinstance(first, Continuity) and isinstance(second, Continuity)
    assert (
        first.relationship.social == "stranger"
        and second.relationship.social == "close_friend"
    )
    assert first.conversation_id != second.conversation_id
    assert len(service.list_grouped()) == 2
    assert DbPersonaRepository(factory).get(request.persona_id).is_frozen


def test_default_setup_racing_start_returns_frozen_original(
    characters_postgres_engine: Engine,
) -> None:
    """Idempotent setup cannot replace or unfreeze a default being first used.

    Args:
        characters_postgres_engine:
            Disposable PostgreSQL database engine.
    """

    factory = _factory(characters_postgres_engine)
    request = _request(factory)
    identities = DbIdentityRepository(factory)
    service = ContinuityService(DbContinuityRepository(factory))
    started, default = _race(lambda: service.start(request), identities.ensure_default)
    assert isinstance(started, Continuity) and isinstance(default, Identity)
    assert default.id == started.identity_id
    assert identities.ensure_default().is_frozen
    assert len(identities.list()) == 1


def test_confirmation_collision_across_pairs_rolls_back_losing_freeze(
    characters_postgres_engine: Engine,
) -> None:
    """The unique confirmation guard covers pairs without shared profile locks.

    Args:
        characters_postgres_engine:
            Disposable PostgreSQL database engine.
    """

    factory = _factory(characters_postgres_engine)
    first_request = _request(factory)
    identity = DbIdentityRepository(factory).create(IdentityDetails(name="Independent"))
    persona = DbPersonaRepository(factory).create(
        PersonaCore(name="Independent", definition="Independent")
    )
    other_request = first_request.model_copy(
        update={"identity_id": identity.id, "persona_id": persona.id}
    )
    service = ContinuityService(DbContinuityRepository(factory))
    outcomes = _race(
        lambda: service.start(first_request), lambda: service.start(other_request)
    )
    assert sum(isinstance(outcome, Continuity) for outcome in outcomes) == 1
    assert (
        sum(isinstance(outcome, ConfirmationConflictError) for outcome in outcomes) == 1
    )
    winner = next(outcome for outcome in outcomes if isinstance(outcome, Continuity))
    for request in [first_request, other_request]:
        won = request.identity_id == winner.identity_id
        assert DbIdentityRepository(factory).get(request.identity_id).is_frozen == won
        assert DbPersonaRepository(factory).get(request.persona_id).is_frozen == won


def test_slice_three_uses_one_revision_with_final_relationship_values(
    characters_postgres_engine: Engine,
) -> None:
    """Upgrade the committed head once and persist the final relationship shape.

    Args:
        characters_postgres_engine:
            Disposable PostgreSQL database engine.
    """

    engine = characters_postgres_engine
    configuration = _configuration(engine)
    history = ScriptDirectory.from_config(configuration)
    revision = history.get_revision("83a2c09d7f41")
    assert revision is not None and revision.down_revision == PRIOR_HEAD
    command.upgrade(configuration, PRIOR_HEAD)
    command.upgrade(configuration, "head")
    command.check(configuration)
    factory = sessionmaker(bind=engine)
    service = ContinuityService(DbContinuityRepository(factory))
    for dynamic in ["neutral", "comfortable", "awkward", "tense", "estranged"]:
        for affection in ["neutral", "warm", "affectionate"]:
            request = _request(factory)
            selection = RelationshipSelection.model_validate(
                {
                    "intent": "platonic",
                    "dynamic": dynamic,
                    "affection": affection,
                }
            )
            request = request.model_copy(update={"relationship": selection})
            created = service.start(request)
            assert (
                service.resume(created.identity_id, created.persona_id, created.id)
                == created
            )
            assert service.start(request) == created
            assert created.relationship.dynamic == dynamic
            assert created.relationship.affection == affection
            with factory() as session:
                state = session.get(StartingRelationshipModel, created.id)
                continuity = session.get(ContinuityModel, created.id)
                assert state is not None and continuity is not None
                assert "familiarity" not in state.snapshot
                assert "familiarity" not in state.snapshot["origins"]
                assert "familiarity" not in continuity.confirmed_request["relationship"]
                assert continuity.confirmed_request == request.model_dump(mode="json")


def _race(first: Callable[[], object], second: Callable[[], object]) -> list[object]:
    """Execute simultaneous operations and retain typed domain outcomes.

    Args:
        first:
            First operation.
        second:
            Competing operation.

    Returns:
        Results or typed expected lifecycle/revision failures in call order.
    """

    barrier = Barrier(2)

    def run(operation: Callable[[], object]) -> object:
        """Wait for the competitor before executing the operation.

        Args:
            operation:
                Callable repository or service action.

        Returns:
            Successful result or expected typed domain error.
        """

        barrier.wait(timeout=10)
        try:
            return operation()
        except (
            ActiveContinuityError,
            ConfirmationConflictError,
            FrozenIdentityError,
            FrozenPersonaError,
            StaleIdentityError,
            StalePersonaError,
        ) as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        return list(executor.map(run, [first, second]))


def _factory(engine: Engine) -> sessionmaker[Session]:
    """Upgrade a disposable database and bind its repository transactions.

    Args:
        engine:
            Disposable PostgreSQL engine.

    Returns:
        Factory bound to the current Characters schema.
    """

    command.upgrade(_configuration(engine), "head")
    return sessionmaker(bind=engine)


def _request(factory: sessionmaker[Session]) -> StartContinuity:
    """Prepare a reviewed request with newly editable profiles.

    Args:
        factory:
            Disposable database session factory.

    Returns:
        Confirmation referring to both current revisions.
    """

    identity = DbIdentityRepository(factory).ensure_default()
    persona = DbPersonaRepository(factory).create(
        PersonaCore(name="Guide", definition="Helpful guide")
    )
    return StartContinuity(
        request_id=uuid4(),
        identity_id=identity.id,
        persona_id=persona.id,
        identity_revision=1,
        persona_revision=1,
        relationship=RelationshipSelection(intent=RelationshipIntent.PLATONIC),
    )


def _configuration(engine: Engine, area: str = "characters") -> Config:
    """Bind area-specific migrations to the disposable database.

    Args:
        engine:
            Disposable PostgreSQL engine.
        area:
            Owning migration area.

    Returns:
        Configured independent Alembic environment.
    """

    configuration = Config(f"alembic-{area}.ini")
    configuration.set_main_option(
        "sqlalchemy.url",
        engine.url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    return configuration


def _chat_snapshot(
    engine: Engine,
) -> tuple[list[Any], list[Any], list[Any], dict[str, list[str]]]:
    """Capture Chat objects, fields, constraints, and all persisted rows.

    Args:
        engine:
            Database holding a populated Chat schema.

    Returns:
        Comparable objects and rows including the Chat version table.
    """

    with engine.connect() as connection:
        objects = list(
            connection.execute(
                text(
                    "SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='chat' ORDER BY 1,2"
                )
            )
        )
        columns = list(
            connection.execute(
                text(
                    "SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema='chat' ORDER BY table_name, ordinal_position"
                )
            )
        )
        constraints = list(
            connection.execute(
                text(
                    "SELECT c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='chat' ORDER BY 1,2"
                )
            )
        )
        rows = {
            table: sorted(
                connection.execute(
                    text(f'SELECT row_to_json(t)::text FROM chat."{table}" t')
                ).scalars()
            )
            for table in inspect(connection).get_table_names(schema="chat")
        }
        return objects, columns, constraints, rows
