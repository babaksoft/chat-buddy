"""Timeline start, navigation, and permanent archive orchestration."""

from time import perf_counter
from uuid import UUID

from chat_buddy.characters.application.calendar import TimelineCalendarPolicy
from chat_buddy.characters.application.diagnostics import (
    NoOpCharactersDiagnosticObserver,
)
from chat_buddy.characters.application.starting_relationship import (
    resolve_starting_relationship,
)
from chat_buddy.characters.domain import (
    ApplicationLocalTimezoneSource,
    CharactersDiagnostic,
    CharactersDiagnosticName,
    CharactersDiagnosticObserver,
    Clock,
    ContinuityMode,
    ConversationGraphRepository,
    DayClosureStatus,
    StartAvailability,
    StartTimeline,
    Timeline,
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
        graphs: ConversationGraphRepository | None = None,
        clock: Clock | None = None,
        diagnostics: CharactersDiagnosticObserver | None = None,
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
            graphs:
                Optional selected-path reader used to observe closure on resume.
            clock:
                Optional injected clock paired with the graph reader.
            diagnostics:
                Optional privacy-safe structured diagnostic sink.

        Raises:
            ValueError:
                If only one closure-observation dependency is supplied.
        """

        if (graphs is None) != (clock is None):
            raise ValueError("Timeline resume closure requires both graph and clock")

        self._timelines = timelines
        self._days = days
        self._timezone_source = timezone_source
        self._calendar = calendar or TimelineCalendarPolicy()
        self._graphs = graphs
        self._clock = clock
        self._diagnostics = diagnostics or NoOpCharactersDiagnosticObserver()

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

        started = perf_counter()
        confirmed = self._timelines.find_reviewed_confirmation(review)
        if confirmed is not None:
            self._emit_start(confirmed, perf_counter() - started)
            return confirmed

        timezone = self._calendar.capture_timezone(self._timezone_source)
        request = StartTimeline.model_validate(
            {
                **review.model_dump(),
                "calendar_timezone": timezone,
            }
        )

        result = self._timelines.start(
            request, resolve_starting_relationship(review.relationship)
        )
        self._emit_start(result, perf_counter() - started)
        return result

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
        timeline = self._observe_latest_closure(timeline)
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

    def _observe_latest_closure(self, timeline: Timeline) -> Timeline:
        """Persist a due latest-day closure during navigation when configured.

        Args:
            timeline:
                Loaded Timeline snapshot.

        Returns:
            Timeline snapshot refreshed after any closure write.
        """

        if self._graphs is None or self._clock is None:
            return timeline

        latest = self._days.latest(timeline)
        if latest is None or latest.is_closed:
            return timeline

        facts = self._calendar.resolve_current(self._clock, timeline.calendar_timezone)
        if facts.current_at < latest.boundary.closes_at:
            return timeline

        selected = self._graphs.selected_path(latest.scope)
        result = self._days.observe_closure(
            latest.scope,
            latest.id,
            facts.current_at,
            timeline.revision,
            selected.selected_leaf_id,
        )
        self._diagnostics.emit(
            CharactersDiagnostic(
                name=CharactersDiagnosticName.TIMELINE_CLOSURE,
                continuity_id=timeline.id,
                conversation_id=latest.scope.conversation_id,
                entry_id=latest.id,
                attempt_id=result.interrupted_attempt_id,
                mode=ContinuityMode.TIMELINE,
                local_date=latest.boundary.local_date,
                boundary_timezone=latest.boundary.timezone,
                policy="timeline_calendar",
                version="1.0.0",
                terminal_reason=result.status.value,
            )
        )
        if result.status in {
            DayClosureStatus.CLOSED,
            DayClosureStatus.CLOSURE_RACE,
            DayClosureStatus.ALREADY_CLOSED,
            DayClosureStatus.STALE_REVISION,
        }:
            return self._timelines.get(
                timeline.identity_id, timeline.persona_id, timeline.id
            )

        return timeline

    def _emit_start(self, result: TimelineStartResult, latency_seconds: float) -> None:
        """Emit one content-free Timeline start outcome.

        Args:
            result:
                Repository start outcome.
            latency_seconds:
                Monotonic start duration.
        """

        timeline = result.timeline
        self._diagnostics.emit(
            CharactersDiagnostic(
                name=CharactersDiagnosticName.TIMELINE_START,
                continuity_id=timeline.id if timeline is not None else None,
                mode=ContinuityMode.TIMELINE,
                boundary_timezone=(
                    timeline.calendar_timezone.name if timeline is not None else None
                ),
                policy="timeline_calendar",
                version="1.0.0",
                terminal_reason=result.status.value,
                latency_seconds=latency_seconds,
            )
        )
