"""PostgreSQL migration and race coverage for Storyline memory persistence."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from chat_buddy.characters.domain import (
    CreateMemoryCommand,
    ExtractionEffect,
    InvalidMemoryDeltaTargetError,
    MemoryDelta,
    SupersedeMemoryCommand,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbMemoryExtractionRepository,
    DbStorylineMemoryRepository,
)
from tests.integration.characters.test_continuity_postgres import _configuration
from tests.integration.characters.test_storyline_memory_repositories import (
    _append_exchange,
    _evidence,
    _parent_id,
    _provenance,
)
from tests.integration.characters.test_storyline_repositories import (
    _complete_exchange,
    _relationship,
    _repositories_and_request,
)

pytestmark = pytest.mark.characters_postgres
PRECEDING_HEAD = "e42b7c91d5a0"


def test_memory_migration_upgrades_downgrades_and_owns_only_characters_schema(
    characters_postgres_engine: Engine,
) -> None:
    """Upgrade from Storylines, inspect ownership, then downgrade and re-upgrade.

    Args:
        characters_postgres_engine:
            Explicit disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    configuration = _configuration(engine)
    command.upgrade(configuration, PRECEDING_HEAD)
    command.upgrade(configuration, "head")
    command.check(configuration)

    inspector = inspect(engine)
    memory_tables = {
        "storyline_memories",
        "memory_revisions",
        "memory_evidence",
        "memory_extraction_effects",
        "memory_conflicts",
    }
    assert memory_tables <= set(inspector.get_table_names(schema="characters"))
    for table in memory_tables:
        assert all(
            foreign_key["referred_schema"] == "characters"
            for foreign_key in inspector.get_foreign_keys(table, schema="characters")
        )

    command.downgrade(configuration, PRECEDING_HEAD)
    assert not memory_tables & set(inspect(engine).get_table_names(schema="characters"))
    command.upgrade(configuration, "head")
    command.check(configuration)


def test_one_effect_reservation_and_one_current_revision_win_under_race(
    characters_postgres_engine: Engine,
) -> None:
    """Serialize source idempotency and competing current-revision replacements.

    Args:
        characters_postgres_engine:
            Explicit disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    command.upgrade(_configuration(engine), "head")
    factory = sessionmaker(bind=engine, autoflush=False)
    storylines, _, request = _repositories_and_request(factory)
    storyline, scene = storylines.start(request, _relationship())
    first_persona_id = _complete_exchange(
        factory, scene.scope.conversation_id, storyline.id
    )

    reservations = _race(
        lambda: DbMemoryExtractionRepository(factory).reserve(
            scene.scope, scene.id, first_persona_id
        ),
        lambda: DbMemoryExtractionRepository(factory).reserve(
            scene.scope, scene.id, first_persona_id
        ),
    )
    assert all(isinstance(outcome, ExtractionEffect) for outcome in reservations)
    first_reservation, second_reservation = reservations
    assert isinstance(first_reservation, ExtractionEffect)
    assert isinstance(second_reservation, ExtractionEffect)
    assert first_reservation.id == second_reservation.id

    extraction = DbMemoryExtractionRepository(factory)
    provenance = _provenance()
    first_evidence = _evidence(
        scene.scope,
        scene.id,
        _parent_id(factory, first_persona_id),
        first_persona_id,
        2,
        provenance,
    )
    effect = first_reservation
    extraction.apply(
        effect.id,
        MemoryDelta(
            selection_id=uuid4(),
            scope=scene.scope,
            source_persona_message_id=first_persona_id,
            extractor=provenance.extractor,
            commands=(
                CreateMemoryCommand(
                    subject="departure time",
                    content="The train leaves at midnight.",
                    occurrence=first_evidence.occurrence,
                    evidence=first_evidence,
                ),
            ),
        ),
        provenance,
    )
    memory = DbStorylineMemoryRepository(factory).list(storyline.id)[0]

    second_user_id, second_persona_id = _append_exchange(factory, scene.scope)
    second_effect = extraction.reserve(scene.scope, scene.id, second_persona_id)
    second_evidence = _evidence(
        scene.scope,
        scene.id,
        second_user_id,
        second_persona_id,
        4,
        provenance,
    )
    third_user_id, third_persona_id = _append_exchange(factory, scene.scope)
    third_effect = extraction.reserve(scene.scope, scene.id, third_persona_id)
    third_evidence = _evidence(
        scene.scope,
        scene.id,
        third_user_id,
        third_persona_id,
        6,
        provenance,
    )

    def replace(
        effect_id: object,
        persona_id: object,
        evidence: object,
        content: str,
    ) -> object:
        """Attempt one guarded automatic replacement.

        Args:
            effect_id:
                Reserved effect identifier.
            persona_id:
                Source persona identifier.
            evidence:
                Exact source evidence.
            content:
                Competing replacement content.

        Returns:
            Terminal extraction effect.
        """

        return DbMemoryExtractionRepository(factory).apply(
            effect_id,  # type: ignore[arg-type]
            MemoryDelta(
                selection_id=uuid4(),
                scope=scene.scope,
                source_persona_message_id=persona_id,  # type: ignore[arg-type]
                extractor=provenance.extractor,
                commands=(
                    SupersedeMemoryCommand(
                        target_memory_id=memory.id,
                        expected_revision_id=memory.current.id,
                        subject="departure time",
                        content=content,
                        occurrence=evidence.occurrence,  # type: ignore[attr-defined]
                        evidence=evidence,  # type: ignore[arg-type]
                    ),
                ),
            ),
            provenance,
        )

    replacements = _race(
        lambda: replace(
            second_effect.id,
            second_persona_id,
            second_evidence,
            "The train leaves at one.",
        ),
        lambda: replace(
            third_effect.id,
            third_persona_id,
            third_evidence,
            "The train leaves at two.",
        ),
    )
    assert sum(isinstance(outcome, ExtractionEffect) for outcome in replacements) == 1
    assert (
        sum(
            isinstance(outcome, InvalidMemoryDeltaTargetError)
            for outcome in replacements
        )
        == 1
    )
    assert (
        len(DbStorylineMemoryRepository(factory).get(storyline.id, memory.id).revisions)
        == 2
    )


def _race(
    first: Callable[[], object], second: Callable[[], object]
) -> tuple[object, object]:
    """Run two callables after a shared barrier and retain domain outcomes.

    Args:
        first:
            First operation.
        second:
            Competing operation.

    Returns:
        Results or raised exceptions in submission order.
    """

    barrier = Barrier(2)

    def invoke(operation: Callable[[], object]) -> object:
        """Synchronize and capture one operation.

        Args:
            operation:
                Operation to invoke.

        Returns:
            Return value or raised exception.
        """

        barrier.wait(timeout=10)
        try:
            return operation()
        except Exception as error:  # noqa: BLE001 - race outcome is asserted.
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (executor.submit(invoke, first), executor.submit(invoke, second))
        return futures[0].result(), futures[1].result()
