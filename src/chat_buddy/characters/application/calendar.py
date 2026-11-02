"""Deterministic Timeline calendar policy based on installed IANA zone data."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from chat_buddy.characters.domain import (
    ApplicationLocalTimezone,
    ApplicationLocalTimezoneSource,
    Clock,
    DayBoundary,
    ResolvedLocalCalendarFacts,
)


class TimelineCalendarPolicy:
    """Resolve captured zones and immutable Timeline day boundaries."""

    def capture_timezone(
        self, source: ApplicationLocalTimezoneSource
    ) -> ApplicationLocalTimezone:
        """Validate the application-local zone supplied at Timeline start.

        Args:
            source:
                Injected application-local timezone source.

        Returns:
            Validated timezone value suitable for immutable capture.
        """

        return ApplicationLocalTimezone(name=source.timezone_name())

    def resolve_current(
        self, clock: Clock, timezone: ApplicationLocalTimezone
    ) -> ResolvedLocalCalendarFacts:
        """Resolve current local and boundary facts from an injected clock.

        Args:
            clock:
                Injected source of the current aware UTC instant.
            timezone:
                Captured Timeline calendar timezone.

        Returns:
            Deterministic local conversion and containing day boundary.

        Raises:
            ValueError:
                If the clock does not return an aware UTC instant.
        """

        current_at = self._require_utc(clock.now())
        zone = ZoneInfo(timezone.name)
        local_at = current_at.astimezone(zone)

        return ResolvedLocalCalendarFacts(
            current_at=current_at,
            local_at=local_at,
            boundary=self.resolve_boundary(local_at.date(), timezone),
        )

    def resolve_boundary(
        self, local_date: date, timezone: ApplicationLocalTimezone
    ) -> DayBoundary:
        """Resolve a representable local date to immutable UTC boundaries.

        Args:
            local_date:
                Civil date to represent.
            timezone:
                Captured Timeline calendar timezone.

        Returns:
            Earliest UTC interval representing the local date.

        Raises:
            ValueError:
                If the civil date is skipped by the timezone.
        """

        zone = ZoneInfo(timezone.name)
        opens_at = self._first_utc_for_date(local_date, zone)
        next_date = local_date + timedelta(days=1)
        while True:
            try:
                closes_at = self._first_utc_for_date(next_date, zone)
                break
            except ValueError:
                next_date += timedelta(days=1)

        return DayBoundary(
            local_date=local_date,
            timezone=timezone.name,
            opens_at=opens_at,
            closes_at=closes_at,
        )

    @staticmethod
    def _require_utc(value: datetime) -> datetime:
        """Validate and normalize an injected UTC instant.

        Args:
            value:
                Candidate clock value.

        Returns:
            UTC-normalized instant.

        Raises:
            ValueError:
                If the value is naive or has a non-zero UTC offset.
        """

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Clock must return a timezone-aware UTC instant")
        if value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("Clock must return a UTC instant")

        return value.astimezone(UTC)

    @staticmethod
    def _first_utc_for_date(local_date: date, zone: ZoneInfo) -> datetime:
        """Find the earliest UTC instant mapping into one civil date.

        The UTC scan locates the transition interval without assuming that local
        midnight exists. A microsecond binary search then finds the exact first
        instant, including historical transitions that did not occur on a whole
        minute.

        Args:
            local_date:
                Candidate civil date.
            zone:
                Installed zone used for conversion.

        Returns:
            Earliest aware UTC instant mapping into the date.

        Raises:
            ValueError:
                If the date was skipped in the zone.
        """

        nominal = datetime.combine(local_date, time.min, tzinfo=UTC)
        cursor = nominal - timedelta(days=2)
        limit = nominal + timedelta(days=2)
        previous = cursor
        while cursor <= limit:
            if cursor.astimezone(zone).date() == local_date:
                return TimelineCalendarPolicy._first_matching_microsecond(
                    previous, cursor, local_date, zone
                )
            previous = cursor
            cursor += timedelta(minutes=1)

        raise ValueError(
            f"Local date {local_date.isoformat()} is not representable in {zone.key}"
        )

    @staticmethod
    def _first_matching_microsecond(
        lower: datetime, upper: datetime, local_date: date, zone: ZoneInfo
    ) -> datetime:
        """Refine a UTC interval to its earliest instant in the target date.

        Args:
            lower:
                Instant at or before the target-date transition.
            upper:
                Known instant within the target date.
            local_date:
                Target civil date.
            zone:
                Installed zone used for conversion.

        Returns:
            Earliest matching instant at datetime microsecond precision.
        """

        if lower.astimezone(zone).date() == local_date:
            upper = lower
            lower -= timedelta(minutes=1)
        lower_us = int(lower.timestamp() * 1_000_000)
        upper_us = int(upper.timestamp() * 1_000_000)
        while lower_us + 1 < upper_us:
            midpoint_us = (lower_us + upper_us) // 2
            midpoint = datetime.fromtimestamp(midpoint_us / 1_000_000, UTC)
            if midpoint.astimezone(zone).date() < local_date:
                lower_us = midpoint_us
            else:
                upper_us = midpoint_us

        return datetime.fromtimestamp(upper_us / 1_000_000, UTC)
