"""Immutable Timeline ownership, day, navigation, and graph-action contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from chat_buddy.characters.domain.branching import GraphActionRequest
from chat_buddy.characters.domain.calendar import ApplicationLocalTimezone, DayBoundary
from chat_buddy.characters.domain.continuity import (
    ContinuityLifecycle,
    RelationshipSelection,
    StartingRelationship,
)
from chat_buddy.characters.domain.conversation import (
    ConversationScope,
    GenerationAttempt,
    Message,
    SubmittedInput,
)
from chat_buddy.characters.domain.llm import EffectiveGeneration
from chat_buddy.characters.domain.response_style import (
    ResponseStyleSettings,
    VersionedResponseStyleSettings,
)


class TimelineStartReview(BaseModel):
    """User-reviewed input for confirming a Timeline start.

    The application-local timezone is deliberately absent. The application
    service captures it only after this review is confirmed.

    Attributes:
        request_id:
            Unique confirmation identifier.
        identity_id:
            Reviewed identity owner.
        persona_id:
            Reviewed persona owner.
        identity_revision:
            Reviewed identity revision.
        persona_revision:
            Reviewed persona revision.
        name:
            User-authored Timeline name.
        relationship:
            Reviewed starting relationship selection.
        response_style:
            Initial requested presentation settings.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    request_id: UUID = Field(description="Confirmation identifier.")
    identity_id: UUID = Field(description="Reviewed identity identifier.")
    persona_id: UUID = Field(description="Reviewed persona identifier.")
    identity_revision: int = Field(ge=1, description="Reviewed identity revision.")
    persona_revision: int = Field(ge=1, description="Reviewed persona revision.")
    name: str = Field(
        min_length=1, max_length=128, description="Authored Timeline name."
    )
    relationship: RelationshipSelection = Field(
        description="Reviewed relationship inputs."
    )
    response_style: ResponseStyleSettings = Field(
        description="Initial requested response-presentation settings."
    )


class StartTimeline(BaseModel):
    """Complete input for an idempotent Timeline start.

    Attributes:
        request_id:
            Unique confirmation identifier.
        identity_id:
            Reviewed identity owner.
        persona_id:
            Reviewed persona owner.
        identity_revision:
            Reviewed identity revision.
        persona_revision:
            Reviewed persona revision.
        name:
            User-authored Timeline name.
        relationship:
            Reviewed starting relationship selection.
        calendar_timezone:
            Automatically resolved application-local zone to capture.
        response_style:
            Initial requested presentation settings.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    request_id: UUID = Field(description="Confirmation identifier.")
    identity_id: UUID = Field(description="Reviewed identity identifier.")
    persona_id: UUID = Field(description="Reviewed persona identifier.")
    identity_revision: int = Field(ge=1, description="Reviewed identity revision.")
    persona_revision: int = Field(ge=1, description="Reviewed persona revision.")
    name: str = Field(
        min_length=1, max_length=128, description="Authored Timeline name."
    )
    relationship: RelationshipSelection = Field(
        description="Reviewed relationship inputs."
    )
    calendar_timezone: ApplicationLocalTimezone = Field(
        description="Automatically resolved application-local calendar zone."
    )
    response_style: ResponseStyleSettings = Field(
        description="Initial requested response-presentation settings."
    )


class Timeline(BaseModel):
    """Detached Timeline snapshot with immutable ownership and calendar zone.

    Attributes:
        id:
            Stable continuity identifier.
        identity_id:
            Permanent identity owner.
        persona_id:
            Permanent persona owner.
        name:
            Current user-authored name.
        lifecycle:
            Writable or permanently archived state.
        relationship:
            Independent starting relationship snapshot.
        calendar_timezone:
            Immutable captured IANA calendar timezone.
        revision:
            Positive optimistic revision for guarded Timeline writes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(description="Stable Timeline continuity identifier.")
    identity_id: UUID = Field(description="Permanent identity owner.")
    persona_id: UUID = Field(description="Permanent persona owner.")
    name: str = Field(
        min_length=1, max_length=128, description="Current Timeline name."
    )
    lifecycle: ContinuityLifecycle = Field(description="Current lifecycle.")
    relationship: StartingRelationship = Field(
        description="Independent starting relationship snapshot."
    )
    calendar_timezone: ApplicationLocalTimezone = Field(
        description="Immutable captured calendar timezone."
    )
    revision: int = Field(ge=1, strict=True, description="Optimistic revision.")


class TimelineGroup(BaseModel):
    """All Timelines for one profile pair with active-slot validation.

    Attributes:
        identity_id:
            Shared identity owner.
        persona_id:
            Shared persona owner.
        timelines:
            Deterministically ordered active and archived Timelines.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity_id: UUID = Field(description="Shared identity owner.")
    persona_id: UUID = Field(description="Shared persona owner.")
    timelines: tuple[Timeline, ...] = Field(
        description="Timelines in stable repository order."
    )

    @model_validator(mode="after")
    def validate_pair_and_active_slot(self) -> Self:
        """Require shared ownership, unique identifiers, and one active Timeline.

        Returns:
            The validated immutable group.

        Raises:
            ValueError:
                If ownership differs, identifiers repeat, or two are active.
        """

        if any(
            timeline.identity_id != self.identity_id
            or timeline.persona_id != self.persona_id
            for timeline in self.timelines
        ):
            raise ValueError("Every Timeline must belong to the supplied pair")
        if len({timeline.id for timeline in self.timelines}) != len(self.timelines):
            raise ValueError("Timeline identifiers must be unique within a pair")
        if (
            sum(
                timeline.lifecycle == ContinuityLifecycle.ACTIVE
                for timeline in self.timelines
            )
            > 1
        ):
            raise ValueError("A profile pair may own at most one active Timeline")
        return self


class TimelineDay(BaseModel):
    """One represented local day with immutable conversation ownership.

    Attributes:
        id:
            Stable represented-day identifier.
        scope:
            Complete Timeline and conversation ownership.
        position:
            Positive immutable order within the Timeline.
        boundary:
            Immutable civil-date and UTC boundary facts.
        closed_at:
            UTC instant when closure was first persisted, if observed.
        settled_selected_leaf_id:
            Selected graph leaf frozen when closure was persisted.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(description="Stable represented-day identifier.")
    scope: ConversationScope = Field(description="Complete day ownership.")
    position: int = Field(ge=1, strict=True, description="Immutable day position.")
    boundary: DayBoundary = Field(description="Immutable calendar boundary facts.")
    closed_at: datetime | None = Field(
        default=None, description="UTC instant when closure was first persisted."
    )
    settled_selected_leaf_id: UUID | None = Field(
        default=None, description="Selected leaf permanently settled at closure."
    )

    @field_validator("closed_at")
    @classmethod
    def validate_closed_at(cls, value: datetime | None) -> datetime | None:
        """Require a persisted closure instant to be aware UTC.

        Args:
            value:
                Candidate closure observation instant.

        Returns:
            UTC-normalized instant or None.

        Raises:
            ValueError:
                If the supplied instant is naive or non-UTC.
        """

        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Day closure instant must be timezone-aware")
        if value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("Day closure instant must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_closure_state(self) -> Self:
        """Require boundary-safe closure with one permanently settled leaf.

        Returns:
            The validated immutable day.

        Raises:
            ValueError:
                If closure timing and settled selection are inconsistent.
        """

        if self.closed_at is not None:
            if self.closed_at < self.boundary.closes_at:
                raise ValueError("A day cannot close before its stored boundary")
            if self.settled_selected_leaf_id is None:
                raise ValueError("A closed day requires its settled selected leaf")
        elif self.settled_selected_leaf_id is not None:
            raise ValueError("An open day cannot settle its selected leaf")
        return self

    @property
    def is_closed(self) -> bool:
        """Return whether closure has been persisted.

        Returns:
            True when a closure observation exists.
        """

        return self.closed_at is not None


class TimelineNavigation(BaseModel):
    """A Timeline and all represented days in immutable navigation order.

    Attributes:
        timeline:
            Owning Timeline snapshot.
        days:
            Represented days, possibly empty before first interaction.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    timeline: Timeline = Field(description="Owning Timeline snapshot.")
    days: tuple[TimelineDay, ...] = Field(description="Ordered represented days.")

    @model_validator(mode="after")
    def validate_day_order(self) -> Self:
        """Require ownership, unique identifiers, dates, and consecutive positions.

        Returns:
            The validated navigation snapshot.

        Raises:
            ValueError:
                If ownership or immutable calendar order is inconsistent.
        """

        expected = (
            self.timeline.identity_id,
            self.timeline.persona_id,
            self.timeline.id,
        )
        if any(
            (
                day.scope.identity_id,
                day.scope.persona_id,
                day.scope.continuity_id,
            )
            != expected
            for day in self.days
        ):
            raise ValueError("Every day must belong to the supplied Timeline")

        if len({day.id for day in self.days}) != len(self.days) or len(
            {day.scope.conversation_id for day in self.days}
        ) != len(self.days):
            raise ValueError("Day and conversation identifiers must be unique")

        if tuple(day.position for day in self.days) != tuple(
            range(1, len(self.days) + 1)
        ):
            raise ValueError("Day positions must be consecutive append order")
        dates = tuple(day.boundary.local_date for day in self.days)
        if dates != tuple(sorted(set(dates))):
            raise ValueError("Represented local dates must increase strictly")

        if any(
            day.boundary.timezone != self.timeline.calendar_timezone.name
            for day in self.days
        ):
            raise ValueError("Every day must use the Timeline calendar timezone")

        if any(day.is_closed is False for day in self.days[:-1]):
            raise ValueError("Only the latest represented day may remain open")
        return self

    @property
    def latest_day(self) -> TimelineDay | None:
        """Return the latest represented day without inventing an empty day.

        Returns:
            Latest day, or None before the first interaction.
        """

        return self.days[-1] if self.days else None


class TimelineStartStatus(StrEnum):
    """Explicit outcomes of an idempotent Timeline start."""

    STARTED = "started"
    IDEMPOTENT = "idempotent"
    ACTIVE_SLOT_CONFLICT = "active_slot_conflict"


class TimelineStartResult(BaseModel):
    """Result of starting a Timeline without exception-only conflict flow.

    Attributes:
        status:
            Stable start outcome.
        timeline:
            New or idempotently existing Timeline when successful.
        style:
            Initial versioned style when successful.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: TimelineStartStatus = Field(description="Stable start outcome.")
    timeline: Timeline | None = Field(description="Successful Timeline snapshot.")
    style: VersionedResponseStyleSettings | None = Field(
        description="Successful initial style snapshot."
    )

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        """Keep success payloads aligned with the explicit outcome.

        Returns:
            The validated result.

        Raises:
            ValueError:
                If success data is missing or attached to a conflict.
        """

        successful = self.status != TimelineStartStatus.ACTIVE_SLOT_CONFLICT
        if successful != (self.timeline is not None and self.style is not None):
            raise ValueError("Only a successful start carries Timeline and style")
        return self


class TimelineRevisionStatus(StrEnum):
    """Explicit outcomes of guarded Timeline or style revisions."""

    UPDATED = "updated"
    IDEMPOTENT = "idempotent"
    STALE_REVISION = "stale_revision"
    ARCHIVED = "archived"


class TimelineRevisionResult(BaseModel):
    """Result of a guarded Timeline metadata or lifecycle revision.

    Attributes:
        status:
            Stable revision outcome.
        timeline:
            Current Timeline snapshot for every outcome.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: TimelineRevisionStatus = Field(description="Stable revision outcome.")
    timeline: Timeline = Field(description="Current Timeline snapshot.")


class ReserveTimelineDay(BaseModel):
    """Guarded request to atomically create a day and its first attempt.

    Attributes:
        timeline_id:
            Expected active Timeline.
        expected_timeline_revision:
            Last observed Timeline revision.
        expected_selected_leaf_id:
            Last observed latest-day selected leaf.
        boundary:
            Resolved current local-day boundary.
        submitted_input:
            Exact first user input.
        generation:
            Effective provider, model, configuration, and budget snapshot.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    timeline_id: UUID = Field(description="Expected active Timeline identifier.")
    expected_timeline_revision: int = Field(
        ge=1, strict=True, description="Last observed Timeline revision."
    )
    expected_selected_leaf_id: UUID | None = Field(
        description="Last observed latest-day selected leaf."
    )
    boundary: DayBoundary = Field(description="Resolved current day boundary.")
    submitted_input: SubmittedInput = Field(description="Exact first user input.")
    generation: EffectiveGeneration = Field(
        description="Effective generation selection for the first attempt."
    )


class DayReservationStatus(StrEnum):
    """Explicit outcomes of an atomic first-send reservation."""

    RESERVED = "reserved"
    STALE_REVISION = "stale_revision"
    STALE_LEAF = "stale_leaf"
    DUPLICATE_DATE = "duplicate_date"
    DAY_CLOSED = "day_closed"
    OPEN_ATTEMPT = "open_attempt"
    ARCHIVED = "archived"


class DayReservationResult(BaseModel):
    """Atomic represented-day, input, and pending-attempt result.

    Attributes:
        status:
            Stable reservation outcome.
        day:
            Newly reserved day on success.
        user_message:
            First committed user message on success.
        attempt:
            First pending generation attempt on success.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: DayReservationStatus = Field(description="Stable reservation outcome.")
    day: TimelineDay | None = Field(description="New day on success.")
    user_message: Message | None = Field(description="First user message on success.")
    attempt: GenerationAttempt | None = Field(description="Pending attempt on success.")

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        """Require the atomic payload only for a successful reservation.

        Returns:
            The validated result.

        Raises:
            ValueError:
                If the result exposes a partial transaction.
        """

        present = (
            self.day is not None,
            self.user_message is not None,
            self.attempt is not None,
        )
        if self.status == DayReservationStatus.RESERVED and not all(present):
            raise ValueError("A reserved day requires its message and attempt")
        if self.status != DayReservationStatus.RESERVED and any(present):
            raise ValueError("A failed reservation cannot expose partial writes")
        return self


class DayClosureStatus(StrEnum):
    """Explicit outcomes of observing a represented-day boundary."""

    STILL_OPEN = "still_open"
    CLOSED = "closed"
    ALREADY_CLOSED = "already_closed"
    STALE_REVISION = "stale_revision"
    CLOSURE_RACE = "closure_race"


class DayClosureResult(BaseModel):
    """Idempotent result of observing and persisting day closure.

    Attributes:
        status:
            Stable closure outcome.
        day:
            Current represented-day snapshot.
        interrupted_attempt_id:
            Open attempt interrupted when closure won the race.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: DayClosureStatus = Field(description="Stable closure outcome.")
    day: TimelineDay = Field(description="Current represented-day snapshot.")
    interrupted_attempt_id: UUID | None = Field(
        default=None, description="Attempt interrupted by persisted closure."
    )

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        """Keep persisted day state aligned with the closure outcome.

        Returns:
            The validated result.

        Raises:
            ValueError:
                If an open outcome carries a closed day or conversely.
        """

        closed_statuses = {
            DayClosureStatus.CLOSED,
            DayClosureStatus.ALREADY_CLOSED,
            DayClosureStatus.CLOSURE_RACE,
        }
        if self.status in closed_statuses and not self.day.is_closed:
            raise ValueError("A closed outcome requires persisted day closure")
        if self.status == DayClosureStatus.STILL_OPEN and self.day.is_closed:
            raise ValueError("A still-open outcome cannot carry a closed day")
        return self


class TimelineGraphActionUnavailableReason(StrEnum):
    """Stable reasons a Timeline day cannot accept a graph action."""

    ARCHIVED_TIMELINE = "archived_timeline"
    NOT_LATEST_DAY = "not_latest_day"
    CLOSED_DAY = "closed_day"


class TimelineGraphActionAvailability(BaseModel):
    """Persistence-neutral authorization facts for one Timeline graph action.

    Attributes:
        timeline_id:
            Expected owning Timeline.
        day_id:
            Day targeted by the guarded graph request.
        day_position:
            Immutable target-day position.
        latest_day_id:
            Persisted latest represented-day identifier.
        latest_day_position:
            Persisted latest represented-day position.
        timeline_lifecycle:
            Current Timeline lifecycle.
        expected_timeline_revision:
            Last observed Timeline revision guarding the action.
        day_is_closed:
            Whether target-day closure has been persisted.
        request:
            Exact guarded graph operation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    timeline_id: UUID = Field(description="Expected owning Timeline identifier.")
    day_id: UUID = Field(description="Target represented-day identifier.")
    day_position: int = Field(ge=1, strict=True, description="Target day position.")
    latest_day_id: UUID = Field(description="Latest represented-day identifier.")
    latest_day_position: int = Field(
        ge=1, strict=True, description="Latest represented-day position."
    )
    timeline_lifecycle: ContinuityLifecycle = Field(
        description="Current Timeline lifecycle."
    )
    expected_timeline_revision: int = Field(
        ge=1, strict=True, description="Last observed Timeline revision."
    )
    day_is_closed: bool = Field(description="Whether closure has been persisted.")
    request: GraphActionRequest = Field(description="Guarded graph operation.")

    @model_validator(mode="after")
    def validate_ownership_and_positions(self) -> Self:
        """Require one owned day at or before the persisted latest day.

        Returns:
            The validated action availability.

        Raises:
            ValueError:
                If ownership or target/latest positions contradict each other.
        """

        if self.request.scope.continuity_id != self.timeline_id:
            raise ValueError("The graph request must belong to the Timeline")
        if self.day_position > self.latest_day_position:
            raise ValueError("A target day cannot be later than the latest day")
        if (
            self.day_position == self.latest_day_position
            and self.day_id != self.latest_day_id
        ):
            raise ValueError("The latest day identifier must match its position")
        if (
            self.day_position < self.latest_day_position
            and self.day_id == self.latest_day_id
        ):
            raise ValueError("An older day cannot use the latest day identifier")
        return self

    @property
    def is_available(self) -> bool:
        """Return whether the action may mutate the latest open day.

        Returns:
            True only for an active Timeline's latest open day.
        """

        return self.unavailable_reason is None

    @property
    def unavailable_reason(self) -> TimelineGraphActionUnavailableReason | None:
        """Return the first stable reason the graph action is unavailable.

        Returns:
            Stable read-only reason, or None when the action is available.
        """

        if self.timeline_lifecycle != ContinuityLifecycle.ACTIVE:
            return TimelineGraphActionUnavailableReason.ARCHIVED_TIMELINE
        if self.day_position != self.latest_day_position:
            return TimelineGraphActionUnavailableReason.NOT_LATEST_DAY
        if self.day_is_closed:
            return TimelineGraphActionUnavailableReason.CLOSED_DAY
        return None
