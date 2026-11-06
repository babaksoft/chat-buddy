"""Focused tests for clock-driven Timeline resume behavior."""

from datetime import UTC, date, datetime
from unittest.mock import Mock
from uuid import uuid4

from chat_buddy.characters.application import TimelineService
from chat_buddy.characters.domain import (
    ApplicationLocalTimezone,
    ContinuityEntry,
    ContinuityLifecycle,
    ContinuityMode,
    DayBoundary,
    DayClosureResult,
    DayClosureStatus,
    RelationshipIntent,
    StartingOrigins,
    StartingRelationship,
    Timeline,
    TimelineDay,
    TimelineNavigation,
)


class FixedClock:
    """Return one deterministic aware UTC instant.

    Attributes:
        value:
            Instant returned by every read.
    """

    def __init__(self, value: datetime) -> None:
        """Initialize the clock.

        Args:
            value:
                Deterministic aware UTC instant.
        """

        self.value = value

    def now(self) -> datetime:
        """Return the configured instant.

        Returns:
            Deterministic aware UTC instant.
        """

        return self.value


class FixedTimezoneSource:
    """Return UTC for starts that are not exercised by this test."""

    def timezone_name(self) -> str:
        """Return the fixed timezone.

        Returns:
            UTC IANA zone.
        """

        return "UTC"


def test_resume_observes_due_latest_day_closure_before_listing() -> None:
    """Persist offline closure with injected time and return refreshed navigation."""

    timeline = _timeline(revision=1)
    refreshed = timeline.model_copy(update={"revision": 2})
    day = _day(timeline)
    closed = day.model_copy(
        update={
            "closed_at": day.boundary.closes_at,
            "settled_selected_leaf_id": uuid4(),
        }
    )
    timelines = Mock()
    days = Mock()
    graphs = Mock()
    timelines.get.side_effect = (timeline, refreshed)
    days.latest.return_value = day
    graphs.selected_path.return_value.selected_leaf_id = uuid4()
    days.observe_closure.return_value = DayClosureResult(
        status=DayClosureStatus.CLOSED, day=closed
    )
    days.list.return_value = TimelineNavigation(timeline=refreshed, days=(closed,))
    service = TimelineService(
        timelines,
        days,
        FixedTimezoneSource(),
        graphs=graphs,
        clock=FixedClock(day.boundary.closes_at),
    )

    result = service.resume(timeline.identity_id, timeline.persona_id, timeline.id)

    graphs.selected_path.assert_called_once_with(day.scope)
    days.observe_closure.assert_called_once_with(
        day.scope,
        day.id,
        day.boundary.closes_at,
        timeline.revision,
        graphs.selected_path.return_value.selected_leaf_id,
    )
    days.list.assert_called_once_with(refreshed)
    assert result.days[0].is_closed


def test_resume_of_empty_timeline_does_not_create_or_resolve_a_day() -> None:
    """Keep refresh and navigation side-effect free before first interaction."""

    timeline = _timeline(revision=1)
    timelines = Mock()
    days = Mock()
    graphs = Mock()
    timelines.get.return_value = timeline
    days.latest.return_value = None
    days.list.return_value = TimelineNavigation(timeline=timeline, days=())
    service = TimelineService(
        timelines,
        days,
        FixedTimezoneSource(),
        graphs=graphs,
        clock=FixedClock(datetime(2026, 11, 7, 12, tzinfo=UTC)),
    )

    result = service.resume(timeline.identity_id, timeline.persona_id, timeline.id)

    assert result.days == ()
    days.observe_closure.assert_not_called()
    graphs.selected_path.assert_not_called()


def _timeline(*, revision: int) -> Timeline:
    """Build a UTC Timeline snapshot.

    Args:
        revision:
            Optimistic revision.

    Returns:
        Immutable Timeline snapshot.
    """

    return Timeline(
        id=uuid4(),
        identity_id=uuid4(),
        persona_id=uuid4(),
        name="Ordinary Days",
        lifecycle=ContinuityLifecycle.ACTIVE,
        relationship=StartingRelationship(
            intent=RelationshipIntent.PLATONIC,
            social="stranger",
            romantic="none",
            dynamic="neutral",
            trust="unknown",
            affection="neutral",
            boundaries=(),
            origins=StartingOrigins(
                social="default",
                romantic="default",
                dynamic="default",
                trust="default",
                affection="default",
                boundaries="default",
            ),
        ),
        calendar_timezone=ApplicationLocalTimezone(name="UTC"),
        revision=revision,
    )


def _day(timeline: Timeline) -> TimelineDay:
    """Build one open represented day.

    Args:
        timeline:
            Owning Timeline.

    Returns:
        Open day with exact UTC boundaries.
    """

    return TimelineDay(
        entry=ContinuityEntry(
            id=uuid4(),
            identity_id=timeline.identity_id,
            persona_id=timeline.persona_id,
            continuity_id=timeline.id,
            conversation_id=uuid4(),
            mode=ContinuityMode.TIMELINE,
            position=1,
        ),
        boundary=DayBoundary(
            local_date=date(2026, 11, 6),
            timezone="UTC",
            opens_at=datetime(2026, 11, 6, tzinfo=UTC),
            closes_at=datetime(2026, 11, 7, tzinfo=UTC),
        ),
        closed_at=None,
        settled_selected_leaf_id=None,
    )
