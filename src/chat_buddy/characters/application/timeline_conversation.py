"""Timeline day adapter for shared conversation orchestration."""

from datetime import datetime

from chat_buddy.characters.application.calendar import TimelineCalendarPolicy
from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    Clock,
    ContinuityLifecycle,
    ContinuityMode,
    ConversationGraphRepository,
    ConversationHistory,
    ConversationTarget,
    DayClosureStatus,
    Timeline,
    TimelineDay,
    TimelineDayReadOnlyError,
    TimelineDayRepository,
    TimelineRepository,
)


class TimelineConversationAdapter:
    """Resolve one Timeline day and enforce its injected-clock write boundary."""

    def __init__(
        self,
        timelines: TimelineRepository,
        days: TimelineDayRepository,
        graphs: ConversationGraphRepository,
        clock: Clock,
        calendar: TimelineCalendarPolicy | None = None,
    ) -> None:
        """Bind Timeline ownership, graph, calendar, and clock dependencies.

        Args:
            timelines:
                Timeline ownership and lifecycle reader.
            days:
                Represented-day and closure repository.
            graphs:
                Selected-path reader used to settle closure.
            clock:
                Injected aware-UTC time source.
            calendar:
                Optional deterministic calendar policy.
        """

        self._timelines = timelines
        self._days = days
        self._graphs = graphs
        self._clock = clock
        self._calendar = calendar or TimelineCalendarPolicy()

    def inspect(
        self, target: ConversationTarget, history: ConversationHistory
    ) -> tuple[Timeline, TimelineDay]:
        """Validate exact Timeline, day, and conversation ownership.

        Args:
            target:
                Exact Timeline day target.
            history:
                Selected history read from the target conversation.

        Returns:
            Owning Timeline and represented day snapshots.

        Raises:
            ValueError:
                If mode, history, or ownership is contradictory.
        """

        if target.mode != ContinuityMode.TIMELINE or target.day_id is None:
            raise ValueError("The Timeline adapter requires a Timeline day target")
        if history.scope != target.scope:
            raise ValueError("Conversation history does not match its target")

        timeline = self._timelines.get(
            target.scope.identity_id,
            target.scope.persona_id,
            target.scope.continuity_id,
        )
        day = self._days.get(target.scope, target.day_id)
        return timeline, day

    def require_writable(
        self, target: ConversationTarget, history: ConversationHistory
    ) -> tuple[Timeline, TimelineDay]:
        """Observe due closure and require the active latest day to remain open.

        Args:
            target:
                Exact Timeline day target.
            history:
                Current selected ancestry and attempts.

        Returns:
            Active Timeline and latest open day.

        Raises:
            ArchivedContinuityError:
                If the Timeline is archived.
            TimelineDayReadOnlyError:
                If the day is closed, nonlatest, or crosses its boundary.
        """

        timeline, day = self.inspect(target, history)
        if timeline.lifecycle != ContinuityLifecycle.ACTIVE:
            raise ArchivedContinuityError("Archived Timelines are read-only")

        latest = self._days.latest(timeline)
        if latest is None or latest.id != day.id:
            raise TimelineDayReadOnlyError(
                "Only the latest represented Timeline day can accept writes"
            )
        if day.is_closed:
            raise TimelineDayReadOnlyError("Closed Timeline days are read-only")

        facts = self._calendar.resolve_current(self._clock, timeline.calendar_timezone)
        self._validate_clock(day, facts.current_at)
        if facts.current_at < day.boundary.closes_at:
            return timeline, day

        selected = self._graphs.selected_path(day.scope)
        result = self._days.observe_closure(
            day.scope,
            day.id,
            facts.current_at,
            timeline.revision,
            selected.selected_leaf_id,
        )
        if result.status == DayClosureStatus.STALE_REVISION:
            timeline = self._timelines.get(
                timeline.identity_id, timeline.persona_id, timeline.id
            )
            refreshed = self._days.get(day.scope, day.id)
            if timeline.lifecycle != ContinuityLifecycle.ACTIVE:
                raise ArchivedContinuityError("Archived Timelines are read-only")
            if refreshed.is_closed:
                raise TimelineDayReadOnlyError("Closed Timeline days are read-only")

            raise TimelineDayReadOnlyError(
                "Timeline state changed while observing the day boundary"
            )

        raise TimelineDayReadOnlyError("Closed Timeline days are read-only")

    @staticmethod
    def _validate_clock(day: TimelineDay, current_at: datetime) -> None:
        """Reject an injected instant that predates committed day facts.

        Args:
            day:
                Represented day with immutable calendar facts.
            current_at:
                Injected aware UTC instant.

        Raises:
            TimelineDayReadOnlyError:
                If the clock moved before a committed boundary fact.
        """

        if current_at < day.boundary.opens_at or (
            day.closed_at is not None and current_at < day.closed_at
        ):
            raise TimelineDayReadOnlyError(
                "The clock predates committed Timeline day facts"
            )
