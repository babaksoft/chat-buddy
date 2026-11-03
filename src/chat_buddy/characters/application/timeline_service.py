"""Timeline start, navigation, and permanent archive orchestration."""

from uuid import UUID

from chat_buddy.characters.application.calendar import TimelineCalendarPolicy
from chat_buddy.characters.application.starting_relationship import (
    resolve_starting_relationship,
)
from chat_buddy.characters.domain import (
    ApplicationLocalTimezoneSource,
    StartAvailability,
    StartTimeline,
    TimelineDayRepository,
    TimelineGroup,
    TimelineNavigation,
    TimelineRepository,
    TimelineRevisionResult,
    TimelineStartResult,
    TimelineStartReview,
)


class TimelineService:
    """Start, inspect, resume, and permanently archive Timelines."""

    def __init__(
        self,
        timelines: TimelineRepository,
        days: TimelineDayRepository,
        timezone_source: ApplicationLocalTimezoneSource,
        calendar: TimelineCalendarPolicy | None = None,
    ) -> None:
        """Initialize Timeline lifecycle operations.

        Args:
            timelines:
                Atomic Timeline ownership repository.
            days:
                Represented-day reader used for stable navigation.
            timezone_source:
                Injected application-local IANA timezone source.
            calendar:
                Optional deterministic calendar policy.
        """

        self._timelines = timelines
        self._days = days
        self._timezone_source = timezone_source
        self._calendar = calendar or TimelineCalendarPolicy()

    def start(self, review: TimelineStartReview) -> TimelineStartResult:
        """Confirm a reviewed Timeline.

        An identical repeated confirmation returns its original captured timezone
        even if the application-local timezone source has since changed.

        Args:
            review:
                Complete user-reviewed profiles, relationship, name, and style.

        Returns:
            Explicit started, idempotent, or active-slot-conflict result.

        Raises:
            ConfirmationConflictError:
                If the confirmation identifier was reused with changed inputs.
            StaleIdentityError:
                If the reviewed identity revision changed before commit.
            StalePersonaError:
                If the reviewed persona revision changed before commit.
            ValueError:
                If the injected application-local timezone is invalid.
        """

        confirmed = self._timelines.find_reviewed_confirmation(review)
        if confirmed is not None:
            return confirmed

        timezone = self._calendar.capture_timezone(self._timezone_source)
        request = StartTimeline.model_validate(
            {
                **review.model_dump(),
                "calendar_timezone": timezone,
            }
        )

        return self._timelines.start(
            request, resolve_starting_relationship(review.relationship)
        )

    def start_availability(
        self, identity_id: UUID, persona_id: UUID
    ) -> StartAvailability:
        """Describe whether the pair has a free active Timeline slot.

        Args:
            identity_id:
                Selected identity owner.
            persona_id:
                Selected persona owner.

        Returns:
            Timeline-specific availability and optional blocking reason.
        """

        if self._timelines.find_active(identity_id, persona_id) is not None:
            return StartAvailability(
                can_start=False,
                reason="Archive the active Timeline before starting another.",
            )

        return StartAvailability(can_start=True)

    def list_grouped(self) -> tuple[TimelineGroup, ...]:
        """List Timelines grouped deterministically by profile pair.

        Returns:
            Stable identity/persona groups including archived history.
        """

        return self._timelines.list()

    def list_for_pair(self, identity_id: UUID, persona_id: UUID) -> TimelineGroup:
        """List active and archived Timelines for one profile pair.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.

        Returns:
            Deterministically ordered Timelines for the pair.
        """

        return self._timelines.list_for_pair(identity_id, persona_id)

    def resume(
        self, identity_id: UUID, persona_id: UUID, timeline_id: UUID
    ) -> TimelineNavigation:
        """Load a Timeline and only its already represented days.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            timeline_id:
                Timeline to resume or inspect.

        Returns:
            Stable navigation snapshot, possibly with no represented days.
        """

        timeline = self._timelines.get(identity_id, persona_id, timeline_id)
        return self._days.list(timeline)

    def archive(
        self,
        identity_id: UUID,
        persona_id: UUID,
        timeline_id: UUID,
        expected_revision: int,
    ) -> TimelineRevisionResult:
        """Permanently archive a Timeline under an optimistic guard.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            timeline_id:
                Timeline to archive.
            expected_revision:
                Last observed Timeline revision.

        Returns:
            Explicit updated, idempotent, or stale revision result.
        """

        return self._timelines.archive(
            identity_id,
            persona_id,
            timeline_id,
            expected_revision,
        )
