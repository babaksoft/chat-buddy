"""Clock-driven Timeline day orchestration coverage."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import (
    TimelineDayService,
    resolve_starting_relationship,
)
from chat_buddy.characters.domain import (
    ApplicationLocalTimezone,
    DayReservationStatus,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.models import (
    ConversationModel,
    GenerationAttemptModel,
    MessageModel,
    ResponseStyleSettingsModel,
    TimelineDayModel,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbConversationRepository,
    DbTimelineDayRepository,
    DbTimelineRepository,
)
from tests.integration.characters.test_timeline_repositories import (
    _generation,
    _request,
)


class MutableClock:
    """Test clock with an explicitly controlled UTC instant.

    Attributes:
        value:
            Current instant returned to the application service.
    """

    def __init__(self, value: datetime) -> None:
        """Initialize the clock.

        Args:
            value:
                Initial aware UTC instant.
        """

        self.value = value

    def now(self) -> datetime:
        """Return the configured instant.

        Returns:
            Current configured instant.
        """

        return self.value


def test_first_send_reuses_today_and_offline_gap_creates_one_next_day(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Close offline history once and omit every non-interacting date.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    request = _request(factory)
    timelines = DbTimelineRepository(factory)
    started = timelines.start(
        request, resolve_starting_relationship(request.relationship)
    )
    assert started.timeline is not None
    timeline = started.timeline
    clock = MutableClock(datetime(2026, 11, 2, 8, tzinfo=UTC))
    service = _service(factory, clock)

    first = service.reserve(
        timeline.identity_id,
        timeline.persona_id,
        timeline.id,
        SubmittedInput(content="Hello today"),
        _generation(),
    )
    reused = service.reserve(
        timeline.identity_id,
        timeline.persona_id,
        timeline.id,
        SubmittedInput(content="A later same-day turn"),
        _generation(),
    )

    assert first.status == DayReservationStatus.RESERVED
    assert first.day is not None
    assert first.attempt is not None
    assert reused.status == DayReservationStatus.REUSED_OPEN_DAY
    assert reused.day == first.day

    clock.value = datetime(2026, 11, 5, 8, tzinfo=UTC)
    after_gap = service.reserve(
        timeline.identity_id,
        timeline.persona_id,
        timeline.id,
        SubmittedInput(content="Back after a few days"),
        _generation(),
    )

    assert after_gap.status == DayReservationStatus.RESERVED
    assert after_gap.day is not None
    assert after_gap.day.position == 2
    assert after_gap.day.boundary.local_date.isoformat() == "2026-11-05"
    navigation = DbTimelineDayRepository(factory).list(
        timelines.get(timeline.identity_id, timeline.persona_id, timeline.id)
    )
    assert tuple(day.boundary.local_date.isoformat() for day in navigation.days) == (
        "2026-11-02",
        "2026-11-05",
    )
    assert navigation.days[0].is_closed
    with factory() as session:
        first_attempt = session.get(GenerationAttemptModel, first.attempt.id)
        assert first_attempt is not None
        assert first_attempt.status == "interrupted"


def test_exact_boundary_closes_day_and_backward_clock_is_rejected(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Treat the closing instant as closed and reject committed-time reversal.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    request = _request(factory)
    timelines = DbTimelineRepository(factory)
    started = timelines.start(
        request, resolve_starting_relationship(request.relationship)
    )
    assert started.timeline is not None
    timeline = started.timeline
    clock = MutableClock(datetime(2026, 11, 2, 8, tzinfo=UTC))
    service = _service(factory, clock)
    first = service.reserve(
        timeline.identity_id,
        timeline.persona_id,
        timeline.id,
        SubmittedInput(content="Before midnight"),
        _generation(),
    )
    assert first.day is not None

    clock.value = first.day.boundary.closes_at
    next_day = service.reserve(
        timeline.identity_id,
        timeline.persona_id,
        timeline.id,
        SubmittedInput(content="At midnight"),
        _generation(),
    )
    assert next_day.status == DayReservationStatus.RESERVED
    assert next_day.day is not None
    assert next_day.day.position == 2

    clock.value = first.day.boundary.closes_at - timedelta(microseconds=1)
    backward = service.reserve(
        timeline.identity_id,
        timeline.persona_id,
        timeline.id,
        SubmittedInput(content="Clock moved backward"),
        _generation(),
    )
    assert backward.status == DayReservationStatus.CLOCK_MOVED_BACKWARD


def test_attempt_reservation_failure_rolls_back_every_day_record(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Leave no day, conversation, or message after attempt setup fails.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    request = _request(factory)
    started = DbTimelineRepository(factory).start(
        request, resolve_starting_relationship(request.relationship)
    )
    assert started.timeline is not None
    timeline = started.timeline
    with factory() as session, session.begin():
        style = session.scalars(select(ResponseStyleSettingsModel)).one()
        session.delete(style)

    service = _service(factory, MutableClock(datetime(2026, 11, 2, 8, tzinfo=UTC)))
    with pytest.raises(NoResultFound):
        service.reserve(
            timeline.identity_id,
            timeline.persona_id,
            timeline.id,
            SubmittedInput(content="This transaction must roll back"),
            _generation(),
        )

    with factory() as session:
        for model in (TimelineDayModel, ConversationModel, MessageModel):
            assert session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize(
    ("current_at", "expected_open", "expected_close"),
    [
        (
            datetime(2026, 3, 8, 12, tzinfo=UTC),
            datetime(2026, 3, 8, 5, tzinfo=UTC),
            datetime(2026, 3, 9, 4, tzinfo=UTC),
        ),
        (
            datetime(2026, 11, 1, 12, tzinfo=UTC),
            datetime(2026, 11, 1, 4, tzinfo=UTC),
            datetime(2026, 11, 2, 5, tzinfo=UTC),
        ),
    ],
)
def test_reservation_uses_captured_zone_across_dst_transitions(
    characters_session_factory: sessionmaker[Session],
    current_at: datetime,
    expected_open: datetime,
    expected_close: datetime,
) -> None:
    """Persist 23- and 25-hour boundaries from the captured Timeline zone.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
        current_at:
            Injected instant within the represented day.
        expected_open:
            Expected immutable UTC opening boundary.
        expected_close:
            Expected immutable UTC closing boundary.
    """

    factory = characters_session_factory
    request = _request(factory).model_copy(
        update={"calendar_timezone": ApplicationLocalTimezone(name="America/New_York")}
    )
    started = DbTimelineRepository(factory).start(
        request, resolve_starting_relationship(request.relationship)
    )
    assert started.timeline is not None
    timeline = started.timeline

    reserved = _service(factory, MutableClock(current_at)).reserve(
        timeline.identity_id,
        timeline.persona_id,
        timeline.id,
        SubmittedInput(content="A day across the clock change"),
        _generation(),
    )

    assert reserved.status == DayReservationStatus.RESERVED
    assert reserved.day is not None
    assert reserved.day.boundary.timezone == "America/New_York"
    assert reserved.day.boundary.opens_at == expected_open
    assert reserved.day.boundary.closes_at == expected_close


def _service(factory: sessionmaker[Session], clock: MutableClock) -> TimelineDayService:
    """Build the orchestration service over database repositories.

    Args:
        factory:
            Isolated Characters database factory.
        clock:
            Injected deterministic clock.

    Returns:
        Configured day orchestration service.
    """

    return TimelineDayService(
        DbTimelineRepository(factory),
        DbTimelineDayRepository(factory),
        DbConversationRepository(factory),
        clock,
    )
