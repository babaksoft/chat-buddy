"""PostgreSQL idempotency coverage for concurrent Timeline evolution."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from alembic import command
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from chat_buddy.characters.application import BASELINE_EVOLUTION_CONFIGURATION
from chat_buddy.characters.domain import EvolutionEffect
from chat_buddy.characters.infrastructure.db.repositories import DbEvolutionRepository
from tests.characters_support import FakeResponse
from tests.integration.characters.test_continuity_postgres import _configuration
from tests.integration.characters.test_evolution_effect_processing import (
    ApplyingEvolutionStrategy,
    _processor,
)
from tests.integration.characters.test_timeline_conversations import (
    FakeSummary,
    MutableClock,
    _start_day,
)
from tests.integration.characters.test_timeline_evolution import _conversation, _source

pytestmark = pytest.mark.characters_postgres


def test_concurrent_timeline_inference_commits_one_effect_and_event(
    characters_postgres_engine: Engine,
) -> None:
    """Serialize repeated inference without duplicating accepted Timeline state.

    Args:
        characters_postgres_engine:
            Explicit disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    command.upgrade(_configuration(engine), "head")
    factory = sessionmaker(bind=engine, autoflush=False)
    clock = MutableClock(datetime(2026, 11, 2, 8, tzinfo=UTC))
    responses = FakeResponse()
    _, target = _start_day(factory, clock, responses, FakeSummary(), "I feel tense")
    app = _conversation(factory, clock, responses)
    list(app.stream(target, app.history(target).attempts[0].id))
    source = _source(factory, target)
    configuration = BASELINE_EVOLUTION_CONFIGURATION.model_copy(
        update={"strategy": ApplyingEvolutionStrategy.strategy_id}
    )
    barrier = Barrier(2)

    def process() -> EvolutionEffect:
        """Process the same committed checkpoint from independent workers.

        Returns:
            The single durable terminal effect.
        """

        processor = _processor(
            factory, configuration, ApplyingEvolutionStrategy(configuration)
        )
        barrier.wait(timeout=10)
        return processor.process(target, source.persona_message_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(process) for _ in range(2)]
        effects = [future.result(timeout=20) for future in futures]
    repository = DbEvolutionRepository(factory)
    assert effects[0].id == effects[1].id
    assert len(repository.list_effects(source.scope)) == 1
    assert len(repository.list_events(source.scope)) == 1
    assert repository.get_projections(source.scope).relationship.revision == 1
