"""Timeline, calendar-fact, and response-style persistence coverage."""

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import resolve_starting_relationship
from chat_buddy.characters.domain import (
    ApplicationLocalTimezone,
    DayBoundary,
    DayClosureStatus,
    DayReservationStatus,
    EffectiveGeneration,
    GenerationConfiguration,
    ModelDescriptor,
    NarrativePlacement,
    PersonaCore,
    RelationshipIntent,
    RelationshipSelection,
    ReserveTimelineDay,
    ResponseContextProvenance,
    ResponseLength,
    ResponseStyleSettings,
    SceneDescriptionLevel,
    StartTimeline,
    StrategyIdentity,
    StyleUpdateStatus,
    SubmittedInput,
    TimelineStartStatus,
)
from chat_buddy.characters.infrastructure.db.models import GenerationAttemptModel
from chat_buddy.characters.infrastructure.db.repositories import (
    DbIdentityRepository,
    DbPersonaRepository,
    DbResponseStyleRepository,
    DbTimelineDayRepository,
    DbTimelineRepository,
)


def test_timeline_day_and_style_state_survive_repository_restart(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Round-trip Timeline ownership, day facts, and attempt style provenance.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    request = _request(factory)
    relationship = resolve_starting_relationship(request.relationship)
    started = DbTimelineRepository(factory).start(request, relationship)

    assert started.status == TimelineStartStatus.STARTED
    assert started.timeline is not None
    assert started.style is not None
    assert started.timeline.calendar_timezone.name == "Asia/Tehran"
    assert DbTimelineRepository(factory).find_confirmation(request) is not None

    styles = DbResponseStyleRepository(factory)
    replacement = ResponseStyleSettings(
        scene_description=SceneDescriptionLevel.RICH,
        response_length=ResponseLength.EXPANSIVE,
        narrative_placement=NarrativePlacement.BEFORE_DIALOGUE,
    )
    updated = styles.update(started.timeline.id, replacement, started.style.revision)
    assert updated.status == StyleUpdateStatus.UPDATED
    assert updated.style.revision == 2

    boundary = DayBoundary(
        local_date=date(2026, 11, 2),
        timezone="Asia/Tehran",
        opens_at=datetime(2026, 11, 1, 20, 30, tzinfo=UTC),
        closes_at=datetime(2026, 11, 2, 20, 30, tzinfo=UTC),
    )
    reserved = DbTimelineDayRepository(factory).reserve_first(
        started.timeline,
        ReserveTimelineDay(
            timeline_id=started.timeline.id,
            expected_timeline_revision=started.timeline.revision,
            expected_selected_leaf_id=None,
            boundary=boundary,
            submitted_input=SubmittedInput(content="Hello today"),
            generation=_generation(),
            response_context=_response_context(),
        ),
    )
    assert reserved.status == DayReservationStatus.RESERVED
    assert reserved.day is not None
    assert reserved.user_message is not None
    assert reserved.attempt is not None

    restarted_days = DbTimelineDayRepository(factory)
    timeline = DbTimelineRepository(factory).get(
        request.identity_id, request.persona_id, started.timeline.id
    )
    assert timeline.revision == 2
    assert restarted_days.list(timeline).days == (reserved.day,)
    with factory() as session:
        attempt = session.scalars(select(GenerationAttemptModel)).one()
        assert attempt.response_style["source_revision"] == 2
        assert attempt.response_style["scene_description"] == "rich"

    closed = restarted_days.observe_closure(
        reserved.day.scope,
        reserved.day.id,
        boundary.closes_at,
        timeline.revision,
        reserved.user_message.id,
    )
    assert closed.status == DayClosureStatus.CLOSED
    assert closed.day.boundary == boundary
    assert closed.day.settled_selected_leaf_id == reserved.user_message.id
    assert closed.interrupted_attempt_id == reserved.attempt.id


def test_timeline_active_slot_and_style_guards_are_explicit(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Return stable active-slot, stale-style, and archived-style outcomes.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    request = _request(factory)
    relationship = resolve_starting_relationship(request.relationship)
    timelines = DbTimelineRepository(factory)
    started = timelines.start(request, relationship)
    assert started.timeline is not None
    assert started.style is not None

    conflict = timelines.start(
        request.model_copy(update={"request_id": uuid4(), "name": "Other"}),
        relationship,
    )
    assert conflict.status == TimelineStartStatus.ACTIVE_SLOT_CONFLICT

    styles = DbResponseStyleRepository(factory)
    stale = styles.update(
        started.timeline.id,
        request.response_style,
        started.style.revision + 1,
    )
    assert stale.status == StyleUpdateStatus.STALE_REVISION
    archived = timelines.archive(
        request.identity_id,
        request.persona_id,
        started.timeline.id,
        started.timeline.revision,
    )
    rejected = styles.update(
        started.timeline.id,
        ResponseStyleSettings(
            scene_description=SceneDescriptionLevel.LIGHT,
            response_length=ResponseLength.CONCISE,
            narrative_placement=NarrativePlacement.AFTER_DIALOGUE,
        ),
        started.style.revision,
    )
    assert archived.timeline.lifecycle.value == "archived"
    assert rejected.status == StyleUpdateStatus.ARCHIVED


def _request(factory: sessionmaker[Session]) -> StartTimeline:
    """Create editable profiles and a reviewed Timeline request.

    Args:
        factory:
            Isolated Characters database factory.

    Returns:
        Complete start request.
    """

    identity = DbIdentityRepository(factory).ensure_default()
    persona = DbPersonaRepository(factory).create(
        PersonaCore(name="Mina", definition="A thoughtful old friend")
    )
    return StartTimeline(
        request_id=uuid4(),
        identity_id=identity.id,
        persona_id=persona.id,
        identity_revision=identity.revision,
        persona_revision=persona.revision,
        name="Ordinary Days",
        relationship=RelationshipSelection(intent=RelationshipIntent.PLATONIC),
        calendar_timezone=ApplicationLocalTimezone(name="Asia/Tehran"),
        response_style=ResponseStyleSettings(
            scene_description=SceneDescriptionLevel.BALANCED,
            response_length=ResponseLength.BALANCED,
            narrative_placement=NarrativePlacement.INTERLEAVED,
        ),
    )


def _generation() -> EffectiveGeneration:
    """Build deterministic response-generation provenance.

    Returns:
        Valid effective response generation.
    """

    return EffectiveGeneration(
        model=ModelDescriptor(
            provider="fake",
            model="test",
            context_tokens=1024,
            output_tokens=128,
            capabilities=frozenset({"response"}),
        ),
        configuration=GenerationConfiguration(max_output_tokens=128),
        capability="response",
        input_tokens=896,
    )


def _response_context() -> ResponseContextProvenance:
    """Build deterministic Timeline response-context provenance.

    Returns:
        Valid Timeline selector and prompt-schema provenance.
    """

    return ResponseContextProvenance(
        selector=StrategyIdentity(
            name="baseline.timeline_response_context", version="1.0.0"
        ),
        prompt_schema_version="1.0.0",
    )
