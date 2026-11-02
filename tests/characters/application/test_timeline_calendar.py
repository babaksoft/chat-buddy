"""Tests for deterministic Timeline calendar resolution."""

from datetime import UTC, date, datetime

import pytest

from chat_buddy.characters.application import TimelineCalendarPolicy
from chat_buddy.characters.domain import ApplicationLocalTimezone


class FixedClock:
    """Test clock returning one configured value."""

    def __init__(self, value: datetime) -> None:
        """Store the configured clock value.

        Args:
            value:
                Value returned by the clock.
        """

        self.value = value

    def now(self) -> datetime:
        """Return the configured value.

        Returns:
            Configured datetime.
        """

        return self.value


class FixedTimezoneSource:
    """Test application-local timezone source."""

    def __init__(self, value: str) -> None:
        """Store the configured zone name.

        Args:
            value:
                Value returned by the source.
        """

        self.value = value

    def timezone_name(self) -> str:
        """Return the configured zone name.

        Returns:
            Configured zone name.
        """

        return self.value


@pytest.mark.parametrize(
    ("local_date", "opens_at", "closes_at"),
    [
        (
            date(2026, 3, 8),
            datetime(2026, 3, 8, 5, tzinfo=UTC),
            datetime(2026, 3, 9, 4, tzinfo=UTC),
        ),
        (
            date(2026, 11, 1),
            datetime(2026, 11, 1, 4, tzinfo=UTC),
            datetime(2026, 11, 2, 5, tzinfo=UTC),
        ),
    ],
)
def test_dst_boundaries_follow_local_calendar(
    local_date: date, opens_at: datetime, closes_at: datetime
) -> None:
    """Resolve 23- and 25-hour New York days without ambiguity."""

    boundary = TimelineCalendarPolicy().resolve_boundary(
        local_date, ApplicationLocalTimezone(name="America/New_York")
    )

    assert boundary.opens_at == opens_at
    assert boundary.closes_at == closes_at


@pytest.mark.parametrize(
    ("zone_name", "local_date", "opens_at", "closes_at"),
    [
        (
            "Asia/Kathmandu",
            date(2026, 2, 28),
            datetime(2026, 2, 27, 18, 15, tzinfo=UTC),
            datetime(2026, 2, 28, 18, 15, tzinfo=UTC),
        ),
        (
            "UTC",
            date(2024, 2, 29),
            datetime(2024, 2, 29, tzinfo=UTC),
            datetime(2024, 3, 1, tzinfo=UTC),
        ),
        (
            "UTC",
            date(2026, 12, 31),
            datetime(2026, 12, 31, tzinfo=UTC),
            datetime(2027, 1, 1, tzinfo=UTC),
        ),
    ],
)
def test_non_hour_leap_day_and_year_rollover_are_exact(
    zone_name: str,
    local_date: date,
    opens_at: datetime,
    closes_at: datetime,
) -> None:
    """Resolve non-hour offsets and civil calendar rollovers exactly."""

    boundary = TimelineCalendarPolicy().resolve_boundary(
        local_date, ApplicationLocalTimezone(name=zone_name)
    )

    assert boundary.opens_at == opens_at
    assert boundary.closes_at == closes_at


def test_current_facts_convert_utc_to_the_captured_local_zone() -> None:
    """Return equivalent local time and Tehran boundary from an injected clock."""

    facts = TimelineCalendarPolicy().resolve_current(
        FixedClock(datetime(2026, 11, 2, 8, tzinfo=UTC)),
        ApplicationLocalTimezone(name="Asia/Tehran"),
    )

    assert facts.local_at.isoformat() == "2026-11-02T11:30:00+03:30"
    assert facts.boundary.local_date == date(2026, 11, 2)
    assert facts.boundary.opens_at == datetime(2026, 11, 1, 20, 30, tzinfo=UTC)
    assert facts.boundary.closes_at == datetime(2026, 11, 2, 20, 30, tzinfo=UTC)


def test_skipped_civil_date_is_rejected() -> None:
    """Reject a date removed by an international-date-line transition."""

    with pytest.raises(ValueError, match="not representable"):
        TimelineCalendarPolicy().resolve_boundary(
            date(2011, 12, 30),
            ApplicationLocalTimezone(name="Pacific/Apia"),
        )


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 1, 1),  # noqa: DTZ001 - deliberately invalid clock value.
        datetime.fromisoformat("2026-01-01T00:00:00+03:30"),
    ],
)
def test_clock_rejects_naive_and_non_utc_values(value: datetime) -> None:
    """Reject clock values whose UTC meaning is not explicit."""

    with pytest.raises(ValueError, match="Clock must return"):
        TimelineCalendarPolicy().resolve_current(
            FixedClock(value), ApplicationLocalTimezone(name="UTC")
        )


def test_timezone_capture_rejects_invalid_injected_zone() -> None:
    """Validate the injected application-local zone at capture time."""

    with pytest.raises(ValueError, match="valid IANA zone"):
        TimelineCalendarPolicy().capture_timezone(FixedTimezoneSource("Mars/Olympus"))
