"""Immutable calendar values and time-source contracts for Timeline."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Clock(Protocol):
    """Supply the current aware UTC instant without consulting system time."""

    def now(self) -> datetime:
        """Return the current aware UTC instant.

        Returns:
            Current aware UTC instant.
        """

        ...


class ApplicationLocalTimezoneSource(Protocol):
    """Supply the application-local IANA timezone captured at Timeline start."""

    def timezone_name(self) -> str:
        """Return the current application-local IANA timezone name.

        Returns:
            Candidate IANA timezone identifier.
        """

        ...


class ApplicationLocalTimezone(BaseModel):
    """Validated application-local timezone captured by a new Timeline.

    Attributes:
        name:
            Installed IANA timezone identifier.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    name: str = Field(
        min_length=1,
        max_length=64,
        description="Installed IANA timezone identifier.",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Reject identifiers that are not installed IANA zones.

        Args:
            value:
                Candidate timezone identifier.

        Returns:
            Validated timezone identifier.

        Raises:
            ValueError:
                If the identifier is not an installed IANA zone.
        """

        if value not in available_timezones():
            raise ValueError("Timezone must be a valid IANA zone")

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Timezone must be a valid IANA zone") from error

        return value


class DayBoundary(BaseModel):
    """Immutable civil-date identity and its resolved UTC interval.

    Attributes:
        local_date:
            Represented local calendar date.
        timezone:
            IANA timezone used to resolve the boundary.
        opens_at:
            Earliest UTC instant mapped into the represented date.
        closes_at:
            Earliest later UTC instant mapped into the next representable date.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    local_date: date = Field(description="Represented local calendar date.")
    timezone: str = Field(
        min_length=1,
        max_length=64,
        description="IANA timezone used to resolve the boundary.",
    )
    opens_at: datetime = Field(description="Aware UTC opening instant.")
    closes_at: datetime = Field(description="Aware UTC closing instant.")

    @field_validator("opens_at", "closes_at")
    @classmethod
    def validate_utc_instant(cls, value: datetime) -> datetime:
        """Require an aware UTC instant and normalize its timezone object.

        Args:
            value:
                Candidate boundary instant.

        Returns:
            UTC-normalized boundary instant.

        Raises:
            ValueError:
                If the timestamp is naive or not expressed in UTC.
        """

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Calendar instants must be timezone-aware")
        if value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("Calendar instants must be UTC")

        return value.astimezone(UTC)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        """Require an installed IANA boundary timezone.

        Args:
            value:
                Candidate timezone identifier.

        Returns:
            Validated timezone identifier.
        """

        return ApplicationLocalTimezone(name=value).name

    @model_validator(mode="after")
    def validate_interval(self) -> DayBoundary:
        """Require ordered boundaries that map to the declared local date.

        Returns:
            Validated boundary.

        Raises:
            ValueError:
                If ordering or local-date provenance is inconsistent.
        """

        if self.opens_at >= self.closes_at:
            raise ValueError("Day closing instant must follow its opening instant")

        zone = ZoneInfo(self.timezone)
        if self.opens_at.astimezone(zone).date() != self.local_date:
            raise ValueError("Day opening instant must map to its local date")
        if self.closes_at.astimezone(zone).date() <= self.local_date:
            raise ValueError("Day closing instant must map after its local date")

        return self


class ResolvedLocalCalendarFacts(BaseModel):
    """Pure calendar facts resolved for one injected current instant.

    Attributes:
        current_at:
            Injected current aware UTC instant.
        local_at:
            Equivalent aware local instant.
        boundary:
            Boundary for the current represented local date.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    current_at: datetime = Field(description="Injected current aware UTC instant.")
    local_at: datetime = Field(description="Equivalent aware local instant.")
    boundary: DayBoundary = Field(description="Resolved current-date boundary.")

    @field_validator("current_at")
    @classmethod
    def validate_current_at(cls, value: datetime) -> datetime:
        """Require an aware UTC current instant.

        Args:
            value:
                Candidate current instant.

        Returns:
            UTC-normalized instant.

        Raises:
            ValueError:
                If the instant is naive or not UTC.
        """

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Current instant must be timezone-aware")
        if value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("Current instant must be UTC")

        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_equivalence(self) -> ResolvedLocalCalendarFacts:
        """Require local and boundary facts to describe the current instant.

        Returns:
            Validated calendar facts.

        Raises:
            ValueError:
                If the local conversion or containing boundary is inconsistent.
        """

        zone = ZoneInfo(self.boundary.timezone)
        if self.local_at.tzinfo is None or self.local_at.utcoffset() is None:
            raise ValueError("Local instant must be timezone-aware")
        if getattr(self.local_at.tzinfo, "key", None) != zone.key:
            raise ValueError("Local instant must use the boundary timezone")
        if self.local_at != self.current_at.astimezone(zone):
            raise ValueError("Local instant must equal the current UTC instant")
        if not self.boundary.opens_at <= self.current_at < self.boundary.closes_at:
            raise ValueError("Current instant must fall within the day boundary")

        return self
