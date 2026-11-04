"""Timeline memory persistence and restart integration tests."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    ContinuityMode,
    CreateMemoryCommand,
    EntryPosition,
    ExtractionProvenance,
    MemoryDelta,
    MemoryEvidence,
    StrategyIdentity,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityMemoryRepository,
    DbMemoryExtractionRepository,
    DbTimelineDayRepository,
)
from tests.characters_support import FakeResponse
from tests.integration.characters.test_timeline_conversations import (
    FakeSummary,
    MutableClock,
    _registry,
    _start_day,
)


def test_timeline_memory_persists_day_provenance_and_as_of_eligibility(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Persist selected day evidence and recover it through a fresh repository.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    clock = MutableClock(datetime(2026, 11, 3, 8, tzinfo=UTC))
    responses = FakeResponse()
    summaries = FakeSummary()
    app, target = _start_day(factory, clock, responses, summaries, "I prefer tea")
    attempt = app.history(target).attempts[0]
    list(app.stream(target, attempt.id))
    history = app.history(target)
    user, persona = history.messages
    assert target.entry_id is not None
    day = DbTimelineDayRepository(factory).get(target.scope, target.entry_id)

    effects = DbMemoryExtractionRepository(factory)
    effect = effects.reserve_timeline(target.scope, day.id, persona.id)
    generation = _registry(responses, summaries).resolve_default("response")
    provenance = ExtractionProvenance(
        selector=StrategyIdentity(name="test.timeline_selector", version="1.0.0"),
        extractor=StrategyIdentity(name="test.timeline_extractor", version="1.0.0"),
        prompt_schema_version="1.0.0",
        provider=generation.model.provider,
        model=generation.model.model,
        configuration=generation.configuration,
    )
    position = EntryPosition(
        entry_id=day.id,
        continuity_id=target.scope.continuity_id,
        mode=ContinuityMode.TIMELINE,
        position=day.position,
    )
    evidence = MemoryEvidence(
        id=uuid4(),
        scope=target.scope,
        entry_id=day.id,
        user_message_id=user.id,
        persona_message_id=persona.id,
        persona_checkpoint=2,
        occurrence=position,
        learned=position,
        extraction=provenance,
        created_at=datetime.now(UTC),
    )
    command = CreateMemoryCommand(
        subject="preferred drink",
        content="The identity prefers tea.",
        occurrence=position,
        evidence=evidence,
    )
    effects.apply(
        effect.id,
        MemoryDelta(
            selection_id=uuid4(),
            scope=target.scope,
            source_persona_message_id=persona.id,
            extractor=provenance.extractor,
            commands=(command,),
        ),
        provenance,
    )

    restarted = DbContinuityMemoryRepository(factory)
    memories = restarted.list_eligible(
        target.scope.continuity_id,
        day.position,
        frozenset({persona.id}),
    )

    assert len(memories) == 1
    assert memories[0].current.source.entry_id == day.id
    assert (
        restarted.list_eligible(
            target.scope.continuity_id,
            day.position,
            frozenset(),
        )
        == ()
    )
    assert restarted.list(uuid4()) == ()
