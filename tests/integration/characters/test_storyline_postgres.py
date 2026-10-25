"""PostgreSQL migration and concurrency acceptance for Storyline persistence."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from chat_buddy.characters.domain import (
    ActiveStorylineError,
    LockedSceneSetupError,
    Scene,
    SceneAppendEligibility,
    SceneSequence,
    StaleStorylineError,
)
from chat_buddy.characters.infrastructure.db.repositories import DbSceneRepository
from tests.integration.characters.test_continuity_postgres import (
    _chat_snapshot,
    _configuration,
)
from tests.integration.characters.test_storyline_repositories import (
    _complete_exchange,
    _next_scene,
    _relationship,
    _repositories_and_request,
)

pytestmark = pytest.mark.characters_postgres
PRIOR_HEAD = "c8d2f41a9b70"


def test_storyline_migration_preserves_stage_five_and_chat_records(
    characters_postgres_engine: Engine,
) -> None:
    """Upgrade populated graphs, attempts, summaries, and Chat without crossing areas.

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
    _insert_stage_five_records(engine)

    command.upgrade(configuration, "head")
    command.check(configuration)
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT mode FROM characters.conversations WHERE id = '44444444-4444-4444-4444-444444444444'"
                )
            )
            == "ongoing"
        )
        expected_counts = {
            "continuities": 1,
            "conversations": 1,
            "messages": 2,
            "generation_attempts": 1,
            "summary_revisions": 1,
        }
        for table, expected in expected_counts.items():
            assert (
                connection.scalar(text(f"SELECT count(*) FROM characters.{table}"))
                == expected
            )
    assert _chat_snapshot(engine) == before
    for table in ("storylines", "scenes"):
        assert all(
            foreign_key["referred_schema"] == "characters"
            for foreign_key in inspect(engine).get_foreign_keys(
                table, schema="characters"
            )
        )

    command.downgrade(configuration, PRIOR_HEAD)
    assert "mode" not in {
        column["name"]
        for column in inspect(engine).get_columns("conversations", schema="characters")
    }
    command.upgrade(configuration, "head")
    command.check(configuration)
    assert _chat_snapshot(engine) == before


def test_concurrent_storyline_start_and_append_have_one_winner(
    characters_postgres_engine: Engine,
) -> None:
    """Serialize the active pair slot and one eligible append revision.

    Args:
        characters_postgres_engine:
            Explicit disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    command.upgrade(_configuration(engine), "head")
    factory = sessionmaker(bind=engine, autoflush=False)
    repository, scenes, request = _repositories_and_request(factory)
    other = request.model_copy(update={"request_id": uuid4()})
    starts = _race(
        lambda: repository.start(request, _relationship()),
        lambda: repository.start(other, _relationship()),
    )
    winners = [outcome for outcome in starts if isinstance(outcome, tuple)]
    assert len(winners) == 1
    assert sum(isinstance(outcome, ActiveStorylineError) for outcome in starts) == 1

    storyline, scene = winners[0]
    setup_writes = _race(
        lambda: scenes.lock_setup(scene.scope, scene.id, None),
        lambda: scenes.replace_setup(
            scene.scope,
            scene.id,
            "A competing first setup.",
            storyline.revision,
        ),
    )
    assert isinstance(setup_writes[0], Scene)
    assert isinstance(setup_writes[1], (Scene, LockedSceneSetupError))
    storyline = repository.get(
        storyline.identity_id, storyline.persona_id, storyline.id
    )
    leaf_id = _complete_exchange(factory, scene.scope.conversation_id, storyline.id)
    eligibility = SceneAppendEligibility(
        storyline_id=storyline.id,
        scene_id=scene.id,
        expected_storyline_revision=storyline.revision,
        expected_selected_leaf_id=leaf_id,
        scene_position=1,
        storyline_lifecycle=storyline.lifecycle,
        is_latest_scene=True,
        has_complete_selected_exchange=True,
        has_unmatched_input=False,
        has_open_attempt=False,
    )
    appends = _race(
        lambda: scenes.append_next(_next_scene(), eligibility),
        lambda: DbSceneRepository(factory).append_next(_next_scene(), eligibility),
    )
    assert sum(isinstance(outcome, SceneSequence) for outcome in appends) == 1
    assert sum(isinstance(outcome, StaleStorylineError) for outcome in appends) == 1
    sequence = next(
        outcome for outcome in appends if isinstance(outcome, SceneSequence)
    )
    repository.archive(
        storyline.identity_id,
        storyline.persona_id,
        storyline.id,
        sequence.storyline.revision,
    )
    replacement, _ = repository.start(
        request.model_copy(update={"request_id": uuid4(), "name": "Replacement"}),
        _relationship(),
    )
    assert replacement.id != storyline.id


def _insert_stage_five_records(engine: Engine) -> None:
    """Populate every Stage 5 Ongoing persistence family before migration.

    Args:
        engine:
            Disposable PostgreSQL engine at the Stage 5 head.
    """

    with engine.begin() as connection:
        connection.execute(text("""
                INSERT INTO characters.identities
                    (id, name, revision, is_frozen)
                VALUES
                    ('22222222-2222-2222-2222-222222222222', 'You', 1, true);
                INSERT INTO characters.personas
                    (id, name, definition, revision, is_frozen)
                VALUES
                    ('33333333-3333-3333-3333-333333333333', 'Guide', 'Helpful', 1, true);
                INSERT INTO characters.continuities
                    (id, identity_id, persona_id, mode, lifecycle, request_id, confirmed_request)
                VALUES (
                    '55555555-5555-5555-5555-555555555555',
                    '22222222-2222-2222-2222-222222222222',
                    '33333333-3333-3333-3333-333333333333',
                    'ongoing', 'active',
                    '66666666-6666-6666-6666-666666666666', '{}'
                );
                INSERT INTO characters.conversations
                    (id, continuity_id, identity_id, persona_id, generation_settings, selected_leaf_id)
                VALUES (
                    '44444444-4444-4444-4444-444444444444',
                    '55555555-5555-5555-5555-555555555555',
                    '22222222-2222-2222-2222-222222222222',
                    '33333333-3333-3333-3333-333333333333', NULL, NULL
                );
                INSERT INTO characters.starting_relationships
                    (continuity_id, identity_id, persona_id, snapshot)
                VALUES (
                    '55555555-5555-5555-5555-555555555555',
                    '22222222-2222-2222-2222-222222222222',
                    '33333333-3333-3333-3333-333333333333', '{}'
                );
                INSERT INTO characters.messages
                    (id, conversation_id, continuity_id, role, content, parent_id, response_provenance, created_at)
                VALUES
                    ('77777777-7777-7777-7777-777777777777',
                     '44444444-4444-4444-4444-444444444444',
                     '55555555-5555-5555-5555-555555555555',
                     'user', 'Hello', NULL, NULL, CURRENT_TIMESTAMP),
                    ('88888888-8888-8888-8888-888888888888',
                     '44444444-4444-4444-4444-444444444444',
                     '55555555-5555-5555-5555-555555555555',
                     'persona', 'Welcome',
                     '77777777-7777-7777-7777-777777777777',
                     '{}', CURRENT_TIMESTAMP);
                UPDATE characters.conversations
                SET selected_leaf_id = '88888888-8888-8888-8888-888888888888'
                WHERE id = '44444444-4444-4444-4444-444444444444';
                INSERT INTO characters.generation_attempts
                    (id, conversation_id, continuity_id, user_message_id,
                     selection_guard_id, persona_message_id, submitted_input,
                     generation, status, incomplete_output, created_at, updated_at,
                     finished_at)
                VALUES (
                    '99999999-9999-9999-9999-999999999999',
                    '44444444-4444-4444-4444-444444444444',
                    '55555555-5555-5555-5555-555555555555',
                    '77777777-7777-7777-7777-777777777777',
                    '77777777-7777-7777-7777-777777777777',
                    '88888888-8888-8888-8888-888888888888',
                    'Hello', '{}', 'completed', 'Welcome',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                );
                INSERT INTO characters.summary_revisions
                    (id, conversation_id, continuity_id, revision, predecessor_id,
                     checkpoint_message_id, content, generation, created_at)
                VALUES (
                    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                    '44444444-4444-4444-4444-444444444444',
                    '55555555-5555-5555-5555-555555555555',
                    1, NULL, '88888888-8888-8888-8888-888888888888',
                    'They greeted each other.', '{}', CURRENT_TIMESTAMP
                );
                """))


def _race(first: Callable[[], object], second: Callable[[], object]) -> list[object]:
    """Execute two Storyline mutations simultaneously and retain typed outcomes.

    Args:
        first:
            First competing operation.
        second:
            Second competing operation.

    Returns:
        Results or expected typed concurrency failures in call order.
    """

    barrier = Barrier(2)

    def run(operation: Callable[[], object]) -> object:
        """Release an operation alongside its competitor.

        Args:
            operation:
                Repository mutation to invoke.

        Returns:
            Successful result or expected typed failure.
        """

        barrier.wait(timeout=10)
        try:
            return operation()
        except (
            ActiveStorylineError,
            LockedSceneSetupError,
            StaleStorylineError,
        ) as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        return list(executor.map(run, (first, second)))
