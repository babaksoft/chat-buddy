"""PostgreSQL concurrency coverage for Storyline conversation reservation."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from alembic import command
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from chat_buddy.characters.application import StorylineService
from chat_buddy.characters.domain import (
    AttemptConflictError,
    GenerationAttempt,
    HistoricalSceneReadOnlyError,
    IncompleteLatestSceneError,
    SceneSequence,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbConversationRepository,
    DbSceneRepository,
    DbStorylineRepository,
)
from tests.characters_support import FakeResponse
from tests.integration.characters.test_continuity_postgres import _configuration
from tests.integration.characters.test_storyline_conversations import (
    _service,
    _target,
)
from tests.integration.characters.test_storyline_repositories import (
    _next_scene,
    _repositories_and_request,
)

pytestmark = pytest.mark.characters_postgres


def test_send_racing_next_scene_append_has_one_writable_scene(
    characters_postgres_engine: Engine,
) -> None:
    """Serialize response reservation against a competing next-scene append.

    Args:
        characters_postgres_engine:
            Explicit disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    command.upgrade(_configuration(engine), "head")
    factory = sessionmaker(bind=engine, autoflush=False)
    storylines, scenes, request = _repositories_and_request(factory)
    lifecycle = StorylineService(storylines, scenes, DbConversationRepository(factory))
    storyline, scene = lifecycle.start(request)
    target = _target(scene.id, scene.scope)
    app = _service(factory, FakeResponse(), storylines, scenes)
    first = app.send(target, SubmittedInput(content="Complete the first exchange"))
    list(app.stream(target, first.id))
    assert scenes.get(scene.scope, scene.id).setup_locked

    eligibility = lifecycle.append_eligibility(
        storyline.identity_id, storyline.persona_id, storyline.id
    )
    barrier = Barrier(2)

    def send() -> object:
        """Reserve another turn after releasing the race barrier.

        Returns:
            Pending attempt or typed concurrency failure.
        """

        barrier.wait(timeout=10)
        try:
            return _service(
                factory,
                FakeResponse(),
                DbStorylineRepository(factory),
                DbSceneRepository(factory),
            ).send(target, SubmittedInput(content="Stay in this scene"))
        except (AttemptConflictError, HistoricalSceneReadOnlyError) as error:
            return error

    def append() -> object:
        """Append the next scene after releasing the race barrier.

        Returns:
            New sequence or typed eligibility failure.
        """

        barrier.wait(timeout=10)
        try:
            return StorylineService(
                DbStorylineRepository(factory),
                DbSceneRepository(factory),
                DbConversationRepository(factory),
            ).append_next(_next_scene(), eligibility)
        except IncompleteLatestSceneError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        send_result, append_result = tuple(
            executor.map(lambda call: call(), (send, append))
        )

    assert isinstance(send_result, GenerationAttempt) != isinstance(
        append_result, SceneSequence
    )
    sequence = DbSceneRepository(factory).list(
        DbStorylineRepository(factory).get(
            storyline.identity_id, storyline.persona_id, storyline.id
        )
    )
    if isinstance(send_result, GenerationAttempt):
        assert len(sequence.scenes) == 1
        assert app.history(target).messages[-1].role == "user"
    else:
        assert len(sequence.scenes) == 2
        assert app.history(target).messages[-1].role == "persona"
