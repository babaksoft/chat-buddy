"""Executable Timeline ownership, day, result, and repository contracts."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from chat_buddy.characters.domain import (
    ApplicationLocalTimezone,
    ContinuityLifecycle,
    ContinuityMode,
    ConversationScope,
    ConversationTarget,
    DayBoundary,
    DayClosureResult,
    DayClosureStatus,
    DayReservationResult,
    DayReservationStatus,
    GraphAction,
    GraphActionRequest,
    NarrativePlacement,
    RelationshipIntent,
    ResponseLength,
    ResponseStyleSettings,
    SceneDescriptionLevel,
    StartingOrigins,
    StartingRelationship,
    StyleUpdateResult,
    StyleUpdateStatus,
    Timeline,
    TimelineDay,
    TimelineGraphActionAvailability,
    TimelineGraphActionUnavailableReason,
    TimelineGroup,
    TimelineNavigation,
    TimelineRevisionResult,
    TimelineRevisionStatus,
    TimelineStartResult,
    TimelineStartStatus,
    VersionedResponseStyleSettings,
)


def _relationship() -> StartingRelationship:
    """Create a valid independent starting relationship.

    Returns:
        Immutable starting relationship fixture.
    """

    return StartingRelationship(
        intent=RelationshipIntent.PLATONIC,
        social="stranger",
        romantic="none",
        dynamic="neutral",
        trust="unknown",
        affection="neutral",
        boundaries=("no_romance",),
        origins=StartingOrigins(
            social="default",
            romantic="default",
            dynamic="default",
            trust="default",
            affection="default",
            boundaries="user_selected",
        ),
    )


def _settings() -> VersionedResponseStyleSettings:
    """Create revision-one Timeline response-style settings.

    Returns:
        Versioned style settings fixture.
    """

    return VersionedResponseStyleSettings(
        settings=ResponseStyleSettings(
            scene_description=SceneDescriptionLevel.BALANCED,
            response_length=ResponseLength.BALANCED,
            narrative_placement=NarrativePlacement.INTERLEAVED,
        ),
        revision=1,
    )


def _timeline(
    *,
    identity_id: UUID | None = None,
    persona_id: UUID | None = None,
    lifecycle: ContinuityLifecycle = ContinuityLifecycle.ACTIVE,
    timezone: str = "UTC",
) -> Timeline:
    """Create a valid Timeline fixture.

    Args:
        identity_id:
            Optional identity owner.
        persona_id:
            Optional persona owner.
        lifecycle:
            Desired lifecycle state.
        timezone:
            Captured IANA calendar zone.

    Returns:
        Immutable Timeline snapshot.
    """

    return Timeline(
        id=uuid4(),
        identity_id=identity_id or uuid4(),
        persona_id=persona_id or uuid4(),
        name="Everyday Roads",
        lifecycle=lifecycle,
        relationship=_relationship(),
        calendar_timezone=ApplicationLocalTimezone(name=timezone),
        revision=1,
    )


def _day(
    timeline: Timeline,
    position: int,
    local_date: date,
    *,
    closed: bool,
) -> TimelineDay:
    """Create one represented UTC day owned by a Timeline.

    Args:
        timeline:
            Owning Timeline.
        position:
            Immutable represented-day position.
        local_date:
            Represented local date.
        closed:
            Whether closure has been persisted.

    Returns:
        Owned represented-day snapshot.
    """

    opens_at = datetime.combine(local_date, datetime.min.time(), tzinfo=UTC)
    closes_at = opens_at + timedelta(days=1)
    return TimelineDay(
        id=uuid4(),
        scope=ConversationScope(
            identity_id=timeline.identity_id,
            persona_id=timeline.persona_id,
            continuity_id=timeline.id,
            conversation_id=uuid4(),
        ),
        position=position,
        boundary=DayBoundary(
            local_date=local_date,
            timezone="UTC",
            opens_at=opens_at,
            closes_at=closes_at,
        ),
        closed_at=closes_at if closed else None,
        settled_selected_leaf_id=uuid4() if closed else None,
    )


def _graph_request(day: TimelineDay) -> GraphActionRequest:
    """Create a guarded Branch-from-here request for one Timeline day.

    Args:
        day:
            Owned represented day.

    Returns:
        Valid guarded graph request.
    """

    return GraphActionRequest(
        scope=day.scope,
        action=GraphAction.BRANCH_FROM_HERE,
        expected_selected_leaf_id=uuid4(),
        target_message_id=uuid4(),
    )


@pytest.mark.parametrize(
    ("mode", "scene_id", "day_id"),
    [
        (ContinuityMode.ONGOING, uuid4(), None),
        (ContinuityMode.ONGOING, None, uuid4()),
        (ContinuityMode.STORYLINE, None, None),
        (ContinuityMode.STORYLINE, uuid4(), uuid4()),
        (ContinuityMode.TIMELINE, None, None),
        (ContinuityMode.TIMELINE, uuid4(), uuid4()),
    ],
)
def test_conversation_targets_reject_invalid_mode_ownership(
    mode: ContinuityMode, scene_id: UUID | None, day_id: UUID | None
) -> None:
    """Require exactly the scene or day owner selected by the mode.

    Args:
        mode:
            Governing continuity mode.
        scene_id:
            Candidate Storyline owner.
        day_id:
            Candidate Timeline owner.
    """

    with pytest.raises(ValidationError):
        ConversationTarget(
            scope=ConversationScope(
                identity_id=uuid4(),
                persona_id=uuid4(),
                continuity_id=uuid4(),
                conversation_id=uuid4(),
            ),
            mode=mode,
            scene_id=scene_id,
            day_id=day_id,
        )


@pytest.mark.parametrize(
    ("mode", "scene_id", "day_id"),
    [
        (ContinuityMode.ONGOING, None, None),
        (ContinuityMode.STORYLINE, uuid4(), None),
        (ContinuityMode.TIMELINE, None, uuid4()),
    ],
)
def test_conversation_targets_accept_exact_mode_ownership(
    mode: ContinuityMode, scene_id: UUID | None, day_id: UUID | None
) -> None:
    """Accept ownerless Ongoing and one owner for each narrative mode.

    Args:
        mode:
            Governing continuity mode.
        scene_id:
            Candidate Storyline owner.
        day_id:
            Candidate Timeline owner.
    """

    target = ConversationTarget(
        scope=ConversationScope(
            identity_id=uuid4(),
            persona_id=uuid4(),
            continuity_id=uuid4(),
            conversation_id=uuid4(),
        ),
        mode=mode,
        scene_id=scene_id,
        day_id=day_id,
    )

    assert target.scene_id == scene_id
    assert target.day_id == day_id


def test_timeline_rejects_invalid_lifecycle_fields_and_is_immutable() -> None:
    """Validate authored bounds, calendar zone, revision, and frozen snapshots."""

    timeline = _timeline()
    with pytest.raises(ValidationError):
        Timeline.model_validate({**timeline.model_dump(), "name": " "})
    with pytest.raises(ValidationError):
        Timeline.model_validate({**timeline.model_dump(), "revision": 0})
    with pytest.raises(ValidationError):
        Timeline.model_validate(
            {
                **timeline.model_dump(),
                "calendar_timezone": {"name": "Not/A_Real_Zone"},
            }
        )
    with pytest.raises(ValidationError):
        Timeline.model_validate(
            {**timeline.model_dump(), "forked_from_timeline_id": uuid4()}
        )
    with pytest.raises(ValidationError):
        timeline.revision = 2


def test_group_enforces_pair_ownership_uniqueness_and_active_slot() -> None:
    """Allow archived history but only one active Timeline per profile pair."""

    identity_id, persona_id = uuid4(), uuid4()
    active = _timeline(identity_id=identity_id, persona_id=persona_id)
    archived = _timeline(
        identity_id=identity_id,
        persona_id=persona_id,
        lifecycle=ContinuityLifecycle.ARCHIVED,
    )

    assert TimelineGroup(
        identity_id=identity_id,
        persona_id=persona_id,
        timelines=(archived, active),
    ).timelines == (archived, active)
    with pytest.raises(ValidationError, match="at most one active"):
        TimelineGroup(
            identity_id=identity_id,
            persona_id=persona_id,
            timelines=(active, active.model_copy(update={"id": uuid4()})),
        )
    with pytest.raises(ValidationError, match="supplied pair"):
        TimelineGroup(
            identity_id=identity_id,
            persona_id=persona_id,
            timelines=(active.model_copy(update={"persona_id": uuid4()}),),
        )


def test_navigation_allows_no_days_and_validates_immutable_day_order() -> None:
    """Represent gaps without placeholders while rejecting invalid order."""

    timeline = _timeline()
    empty = TimelineNavigation(timeline=timeline, days=())
    first = _day(timeline, 1, date(2026, 11, 2), closed=True)
    second = _day(timeline, 2, date(2026, 11, 5), closed=False)

    navigation = TimelineNavigation(timeline=timeline, days=(first, second))

    assert empty.latest_day is None
    assert navigation.latest_day == second
    with pytest.raises(ValidationError, match="consecutive"):
        TimelineNavigation(
            timeline=timeline,
            days=(first, second.model_copy(update={"position": 3})),
        )
    with pytest.raises(ValidationError, match="increase strictly"):
        TimelineNavigation(
            timeline=timeline,
            days=(first, second.model_copy(update={"boundary": first.boundary})),
        )
    with pytest.raises(ValidationError, match="latest"):
        TimelineNavigation(
            timeline=timeline,
            days=(
                first.model_copy(
                    update={"closed_at": None, "settled_selected_leaf_id": None}
                ),
                second,
            ),
        )


def test_navigation_rejects_foreign_ownership_and_calendar_zone() -> None:
    """Keep every represented day inside one Timeline and captured zone."""

    timeline = _timeline()
    day = _day(timeline, 1, date(2026, 11, 2), closed=False)
    foreign_scope = day.scope.model_copy(update={"continuity_id": uuid4()})

    with pytest.raises(ValidationError, match="supplied Timeline"):
        TimelineNavigation(
            timeline=timeline,
            days=(day.model_copy(update={"scope": foreign_scope}),),
        )

    tehran_timeline = timeline.model_copy(
        update={"calendar_timezone": ApplicationLocalTimezone(name="Asia/Tehran")}
    )
    with pytest.raises(ValidationError, match="calendar timezone"):
        TimelineNavigation(timeline=tehran_timeline, days=(day,))


def test_day_closure_cannot_precede_boundary() -> None:
    """Persist closure only after the boundary with one settled selected leaf."""

    timeline = _timeline()
    day = _day(timeline, 1, date(2026, 11, 2), closed=False)

    with pytest.raises(ValidationError, match="before"):
        TimelineDay.model_validate(
            {
                **day.model_dump(),
                "closed_at": day.boundary.closes_at - timedelta(microseconds=1),
                "settled_selected_leaf_id": uuid4(),
            }
        )
    with pytest.raises(ValidationError, match="requires its settled"):
        TimelineDay.model_validate(
            {**day.model_dump(), "closed_at": day.boundary.closes_at}
        )
    with pytest.raises(ValidationError, match="open day cannot settle"):
        TimelineDay.model_validate(
            {**day.model_dump(), "settled_selected_leaf_id": uuid4()}
        )


def test_start_and_revision_results_expose_conflicts_explicitly() -> None:
    """Keep active-slot and stale revision outcomes in typed results."""

    timeline = _timeline()
    conflict = TimelineStartResult(
        status=TimelineStartStatus.ACTIVE_SLOT_CONFLICT,
        timeline=None,
        style=None,
    )
    stale = TimelineRevisionResult(
        status=TimelineRevisionStatus.STALE_REVISION,
        timeline=timeline,
    )
    stale_style = StyleUpdateResult(
        status=StyleUpdateStatus.STALE_REVISION,
        style=_settings(),
    )

    assert conflict.status == TimelineStartStatus.ACTIVE_SLOT_CONFLICT
    assert stale.timeline == timeline
    assert stale_style.status == StyleUpdateStatus.STALE_REVISION
    with pytest.raises(ValidationError, match="successful start"):
        TimelineStartResult(
            status=TimelineStartStatus.STARTED,
            timeline=timeline,
            style=None,
        )
    with pytest.raises(ValidationError, match="successful start"):
        TimelineStartResult(
            status=TimelineStartStatus.ACTIVE_SLOT_CONFLICT,
            timeline=timeline,
            style=_settings(),
        )


def test_failed_day_reservation_cannot_expose_partial_writes() -> None:
    """Represent duplicate dates and stale leaves without partial records."""

    duplicate = DayReservationResult(
        status=DayReservationStatus.DUPLICATE_DATE,
        day=None,
        user_message=None,
        attempt=None,
    )

    assert duplicate.status == DayReservationStatus.DUPLICATE_DATE
    with pytest.raises(ValidationError, match="partial writes"):
        DayReservationResult(
            status=DayReservationStatus.STALE_LEAF,
            day=_day(_timeline(), 1, date(2026, 11, 2), closed=False),
            user_message=None,
            attempt=None,
        )


def test_closure_result_aligns_status_with_persisted_state() -> None:
    """Expose closure races while keeping day state self-consistent."""

    timeline = _timeline()
    open_day = _day(timeline, 1, date(2026, 11, 2), closed=False)
    closed_day = open_day.model_copy(
        update={
            "closed_at": open_day.boundary.closes_at,
            "settled_selected_leaf_id": uuid4(),
        }
    )

    result = DayClosureResult(
        status=DayClosureStatus.CLOSURE_RACE,
        day=closed_day,
        interrupted_attempt_id=uuid4(),
    )

    assert result.day.is_closed
    with pytest.raises(ValidationError, match="requires persisted"):
        DayClosureResult(status=DayClosureStatus.CLOSED, day=open_day)
    with pytest.raises(ValidationError, match="cannot carry"):
        DayClosureResult(status=DayClosureStatus.STILL_OPEN, day=closed_day)


def test_latest_open_day_allows_guarded_graph_actions() -> None:
    """Authorize graph mutation only for an active Timeline's latest open day."""

    timeline = _timeline()
    day = _day(timeline, 2, date(2026, 11, 3), closed=False)
    availability = TimelineGraphActionAvailability(
        timeline_id=timeline.id,
        day_id=day.id,
        day_position=day.position,
        latest_day_id=day.id,
        latest_day_position=day.position,
        timeline_lifecycle=timeline.lifecycle,
        expected_timeline_revision=timeline.revision,
        day_is_closed=day.is_closed,
        request=_graph_request(day),
    )

    assert availability.is_available
    assert availability.unavailable_reason is None


@pytest.mark.parametrize(
    ("lifecycle", "day_position", "latest_position", "closed", "reason"),
    [
        (
            ContinuityLifecycle.ARCHIVED,
            2,
            2,
            False,
            TimelineGraphActionUnavailableReason.ARCHIVED_TIMELINE,
        ),
        (
            ContinuityLifecycle.ACTIVE,
            1,
            2,
            False,
            TimelineGraphActionUnavailableReason.NOT_LATEST_DAY,
        ),
        (
            ContinuityLifecycle.ACTIVE,
            2,
            2,
            True,
            TimelineGraphActionUnavailableReason.CLOSED_DAY,
        ),
    ],
)
def test_historical_graph_actions_return_stable_unavailable_reasons(
    lifecycle: ContinuityLifecycle,
    day_position: int,
    latest_position: int,
    closed: bool,
    reason: TimelineGraphActionUnavailableReason,
) -> None:
    """Fail closed without offering a Timeline fork-required outcome.

    Args:
        lifecycle:
            Current Timeline lifecycle.
        day_position:
            Target represented-day position.
        latest_position:
            Persisted latest represented-day position.
        closed:
            Whether target closure is persisted.
        reason:
            Expected stable unavailable reason.
    """

    timeline = _timeline(lifecycle=lifecycle)
    day = _day(timeline, day_position, date(2026, 11, 2), closed=closed)
    latest_day_id = day.id if day_position == latest_position else uuid4()
    availability = TimelineGraphActionAvailability(
        timeline_id=timeline.id,
        day_id=day.id,
        day_position=day_position,
        latest_day_id=latest_day_id,
        latest_day_position=latest_position,
        timeline_lifecycle=lifecycle,
        expected_timeline_revision=timeline.revision,
        day_is_closed=closed,
        request=_graph_request(day),
    )

    assert not availability.is_available
    assert availability.unavailable_reason == reason


def test_graph_action_availability_rejects_foreign_or_impossible_day_facts() -> None:
    """Reject foreign ownership and contradictory immutable day positions."""

    timeline = _timeline()
    day = _day(timeline, 1, date(2026, 11, 2), closed=False)
    values = {
        "timeline_id": timeline.id,
        "day_id": day.id,
        "day_position": 1,
        "latest_day_id": day.id,
        "latest_day_position": 1,
        "timeline_lifecycle": timeline.lifecycle,
        "expected_timeline_revision": timeline.revision,
        "day_is_closed": False,
        "request": _graph_request(day),
    }

    with pytest.raises(ValidationError, match="belong to the Timeline"):
        TimelineGraphActionAvailability.model_validate(
            {**values, "timeline_id": uuid4()}
        )
    with pytest.raises(ValidationError, match="later than the latest"):
        TimelineGraphActionAvailability.model_validate({**values, "day_position": 2})
    with pytest.raises(ValidationError, match="identifier must match"):
        TimelineGraphActionAvailability.model_validate(
            {**values, "latest_day_id": uuid4()}
        )
    with pytest.raises(ValidationError, match="older day"):
        TimelineGraphActionAvailability.model_validate(
            {**values, "latest_day_position": 2}
        )
