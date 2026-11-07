"""Clock-driven Timeline day closure and first-interaction orchestration."""

from datetime import datetime
from uuid import UUID

from chat_buddy.characters.application.calendar import TimelineCalendarPolicy
from chat_buddy.characters.application.context_service import TimelineContextBudgeter
from chat_buddy.characters.application.diagnostics import (
    NoOpCharactersDiagnosticObserver,
)
from chat_buddy.characters.domain import (
    CharactersDiagnostic,
    CharactersDiagnosticName,
    CharactersDiagnosticObserver,
    Clock,
    ContinuityLifecycle,
    ContinuityMode,
    ConversationGraphRepository,
    DayClosureStatus,
    DayReservationResult,
    DayReservationStatus,
    EffectiveGeneration,
    ReserveTimelineDay,
    ResponseContextProvenance,
    SubmittedInput,
    Timeline,
    TimelineDay,
    TimelineDayRepository,
    TimelineRepository,
)
from chat_buddy.characters.prompts import TIMELINE_RESPONSE_PROMPT_SCHEMA_VERSION


class TimelineDayService:
    """Resolve one writable Timeline day from an injected UTC clock."""

    def __init__(
        self,
        timelines: TimelineRepository,
        days: TimelineDayRepository,
        graphs: ConversationGraphRepository,
        clock: Clock,
        calendar: TimelineCalendarPolicy | None = None,
        diagnostics: CharactersDiagnosticObserver | None = None,
    ) -> None:
        """Initialize deterministic day orchestration.

        Args:
            timelines:
                Timeline ownership and optimistic-revision repository.
            days:
                Atomic day closure and first-reservation repository.
            graphs:
                Selected-path reader used to guard closure.
            clock:
                Injected source of aware UTC instants.
            calendar:
                Optional deterministic calendar policy.
            diagnostics:
                Optional privacy-safe structured diagnostic sink.
        """

        self._timelines = timelines
        self._days = days
        self._graphs = graphs
        self._clock = clock
        self._calendar = calendar or TimelineCalendarPolicy()
        self._diagnostics = diagnostics or NoOpCharactersDiagnosticObserver()

    def reserve(
        self,
        identity_id: UUID,
        persona_id: UUID,
        timeline_id: UUID,
        submitted_input: SubmittedInput,
        generation: EffectiveGeneration,
    ) -> DayReservationResult:
        """Reuse today's open day or reserve the first interaction atomically.

        Closure is observed before the current local date is considered. An
        existing open day is returned without appending another input; the
        conversation service owns subsequent same-day turns.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            timeline_id:
                Timeline accepting the operation.
            submitted_input:
                Exact input for a newly represented day.
            generation:
                Effective generation snapshot for its pending attempt.

        Returns:
            Explicit reserved, reused, archived, clock, or race outcome.
        """

        timeline = self._timelines.get(identity_id, persona_id, timeline_id)
        if timeline.lifecycle != ContinuityLifecycle.ACTIVE:
            return self._failed(DayReservationStatus.ARCHIVED)

        facts = self._calendar.resolve_current(self._clock, timeline.calendar_timezone)
        latest = self._days.latest(timeline)
        if latest is not None:
            if self._clock_moved_backward(latest, facts.current_at):
                return self._failed(DayReservationStatus.CLOCK_MOVED_BACKWARD)

            timeline, latest = self._observe_closure(timeline, latest, facts.current_at)
            if latest is None:
                return self._failed(DayReservationStatus.STALE_REVISION)
            if timeline.lifecycle != ContinuityLifecycle.ACTIVE:
                return self._failed(DayReservationStatus.ARCHIVED)
            if self._clock_moved_backward(latest, facts.current_at):
                return self._failed(DayReservationStatus.CLOCK_MOVED_BACKWARD)
            if facts.boundary.local_date == latest.boundary.local_date:
                if latest.is_closed:
                    return self._failed(DayReservationStatus.CLOCK_MOVED_BACKWARD)
                return DayReservationResult(
                    status=DayReservationStatus.REUSED_OPEN_DAY,
                    day=latest,
                    user_message=None,
                    attempt=None,
                )

            if facts.boundary.local_date < latest.boundary.local_date:
                return self._failed(DayReservationStatus.CLOCK_MOVED_BACKWARD)
            if not latest.is_closed:
                return self._failed(DayReservationStatus.STALE_REVISION)

        expected_leaf_id = None if latest is None else latest.settled_selected_leaf_id
        request = ReserveTimelineDay(
            timeline_id=timeline.id,
            expected_timeline_revision=timeline.revision,
            expected_selected_leaf_id=expected_leaf_id,
            boundary=facts.boundary,
            submitted_input=submitted_input,
            generation=generation,
            response_context=ResponseContextProvenance(
                selector=TimelineContextBudgeter().selector,
                prompt_schema_version=TIMELINE_RESPONSE_PROMPT_SCHEMA_VERSION,
            ),
        )

        result = self._days.reserve_first(timeline, request)
        day = result.day
        self._diagnostics.emit(
            CharactersDiagnostic(
                name=CharactersDiagnosticName.TIMELINE_DAY_RESERVATION,
                continuity_id=timeline.id,
                conversation_id=day.scope.conversation_id if day is not None else None,
                entry_id=day.id if day is not None else None,
                attempt_id=result.attempt.id if result.attempt is not None else None,
                mode=ContinuityMode.TIMELINE,
                local_date=request.boundary.local_date,
                boundary_timezone=request.boundary.timezone,
                policy=request.response_context.selector.name,
                version=request.response_context.selector.version,
                terminal_reason=result.status.value,
            )
        )
        return result

    def _observe_closure(
        self, timeline: Timeline, latest: TimelineDay, current_at: datetime
    ) -> tuple[Timeline, TimelineDay | None]:
        """Persist due closure and refresh revision after a closure write.

        Args:
            timeline:
                Last observed Timeline.
            latest:
                Last represented day.
            current_at:
                Current UTC instant resolved by the calendar policy.

        Returns:
            Current Timeline and latest day, or a missing latest day after a race.
        """

        if latest.is_closed or current_at < latest.boundary.closes_at:
            return timeline, latest

        selected = self._graphs.selected_path(latest.scope)
        result = self._days.observe_closure(
            latest.scope,
            latest.id,
            current_at,
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
        if result.status == DayClosureStatus.STALE_REVISION:
            refreshed = self._timelines.get(
                timeline.identity_id, timeline.persona_id, timeline.id
            )
            return refreshed, self._days.latest(refreshed)
        if result.status == DayClosureStatus.STILL_OPEN:
            return timeline, result.day

        refreshed = self._timelines.get(
            timeline.identity_id, timeline.persona_id, timeline.id
        )
        return refreshed, result.day

    @staticmethod
    def _clock_moved_backward(latest: TimelineDay, current_at: datetime) -> bool:
        """Return whether current time contradicts committed calendar facts.

        Args:
            latest:
                Latest represented day.
            current_at:
                Current UTC instant resolved by the calendar policy.

        Returns:
            True when the instant predates the day or its closure observation.
        """

        return current_at < latest.boundary.opens_at or (
            latest.closed_at is not None and current_at < latest.closed_at
        )

    @staticmethod
    def _failed(status: DayReservationStatus) -> DayReservationResult:
        """Build a payload-free unsuccessful resolution.

        Args:
            status:
                Stable unsuccessful outcome.

        Returns:
            Validated result without partial writes.
        """

        return DayReservationResult(
            status=status, day=None, user_message=None, attempt=None
        )
