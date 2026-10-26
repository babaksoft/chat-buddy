"""PostgreSQL concurrency coverage for structural Storyline forks."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from chat_buddy.characters.application import StorylineForkService
from chat_buddy.characters.domain import StorylineForkConflictError, StorylineForkResult
from chat_buddy.characters.infrastructure.db.repositories import (
    DbConversationRepository,
    DbIdentityRepository,
    DbPersonaRepository,
    DbStorylineForkRepository,
)
from tests.integration.characters.test_continuity_postgres import _configuration
from tests.integration.characters.test_storyline_forks import _prepared_older_scene

pytestmark = pytest.mark.characters_postgres


def test_concurrent_fork_confirmation_is_idempotent_and_pair_safe(
    characters_postgres_engine: Engine,
) -> None:
    """Return one fork for one request and one winner for competing requests.

    Args:
        characters_postgres_engine:
            Explicit disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    command.upgrade(_configuration(engine), "head")
    factory = sessionmaker(bind=engine, autoflush=False)
    (
        storylines,
        scenes,
        _,
        source_storyline,
        _,
        source_target,
        _,
        first_response_id,
        source_leaf_id,
    ) = _prepared_older_scene(factory)
    identities = DbIdentityRepository(factory)
    personas = DbPersonaRepository(factory)
    duplicate = identities.create(identities.get(source_storyline.identity_id).details)
    service = StorylineForkService(
        storylines,
        scenes,
        DbConversationRepository(factory),
        DbConversationRepository(factory),
        identities,
        personas,
        DbStorylineForkRepository(factory),
    )
    preview = service.preview(
        request_id=uuid4(),
        name="Concurrent fork",
        target=source_target,
        branch_point_message_id=first_response_id,
        expected_selected_leaf_id=source_leaf_id,
        expected_storyline_revision=source_storyline.revision + 1,
        target_identity_id=duplicate.id,
        target_persona_id=source_storyline.persona_id,
    )

    repeated = _race(lambda: service.confirm(preview), lambda: service.confirm(preview))
    assert all(isinstance(outcome, StorylineForkResult) for outcome in repeated)
    first, second = repeated
    assert isinstance(first, StorylineForkResult)
    assert isinstance(second, StorylineForkResult)
    assert first.storyline.id == second.storyline.id

    competing_duplicate = identities.create(
        identities.get(source_storyline.identity_id).details
    )
    competing = tuple(
        service.preview(
            request_id=uuid4(),
            name=name,
            target=source_target,
            branch_point_message_id=first_response_id,
            expected_selected_leaf_id=source_leaf_id,
            expected_storyline_revision=source_storyline.revision + 1,
            target_identity_id=competing_duplicate.id,
            target_persona_id=source_storyline.persona_id,
        )
        for name in ("First contender", "Second contender")
    )
    contenders = _race(
        lambda: service.confirm(competing[0]),
        lambda: service.confirm(competing[1]),
    )
    assert sum(isinstance(outcome, StorylineForkResult) for outcome in contenders) == 1
    assert (
        sum(isinstance(outcome, StorylineForkConflictError) for outcome in contenders)
        == 1
    )


def _race(
    first: Callable[[], object], second: Callable[[], object]
) -> tuple[object, object]:
    """Run two zero-argument callables after a shared barrier.

    Args:
        first:
            First callable operation.
        second:
            Second callable operation.

    Returns:
        Each return value or raised exception in submission order.
    """

    barrier = Barrier(2)

    def invoke(operation: Callable[[], object]) -> object:
        """Wait for the peer and capture a result or exception.

        Args:
            operation:
                Zero-argument callable.

        Returns:
            Callable result or raised exception.
        """

        barrier.wait()
        try:
            return operation()
        except Exception as error:  # noqa: BLE001 - race outcome is asserted.
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (executor.submit(invoke, first), executor.submit(invoke, second))
        return futures[0].result(), futures[1].result()
