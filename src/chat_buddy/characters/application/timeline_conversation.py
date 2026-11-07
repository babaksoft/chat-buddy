"""Timeline day adapter for shared conversation orchestration."""

from datetime import datetime
from uuid import UUID

from chat_buddy.characters.application.calendar import TimelineCalendarPolicy
from chat_buddy.characters.application.diagnostics import (
    NoOpCharactersDiagnosticObserver,
)
from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    BranchModeFacts,
    CharactersDiagnostic,
    CharactersDiagnosticName,
    CharactersDiagnosticObserver,
    Clock,
    ContinuityLifecycle,
    ContinuityMode,
    ConversationGraphRepository,
    ConversationHistory,
    ConversationScope,
    ConversationTarget,
    DayClosureStatus,
    Timeline,
    TimelineDay,
    TimelineDayReadOnlyError,
    TimelineDayRepository,
    TimelineGraphActionUnavailableReason,
    TimelineRepository,
    TimelineWriteGuard,
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
        diagnostics: CharactersDiagnosticObserver | None = None,
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
            diagnostics:
                Optional privacy-safe structured diagnostic sink.
        """

        self._timelines = timelines
        self._days = days
        self._graphs = graphs
        self._clock = clock
        self._calendar = calendar or TimelineCalendarPolicy()
        self._diagnostics = diagnostics or NoOpCharactersDiagnosticObserver()

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

        if target.mode != ContinuityMode.TIMELINE or target.entry_id is None:
            raise ValueError("The Timeline adapter requires a Timeline day target")
        if history.scope != target.scope:
            raise ValueError("Conversation history does not match its target")

        timeline = self._timelines.get(
            target.scope.identity_id,
            target.scope.persona_id,
            target.scope.continuity_id,
        )
        day = self._days.get(target.scope, target.entry_id)
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

        timeline, day, _ = self._require_writable(target, history)
        return timeline, day

    def write_guard(
        self, target: ConversationTarget, history: ConversationHistory
    ) -> TimelineWriteGuard:
        """Resolve closure and capture facts for the immediate write transaction.

        Args:
            target:
                Exact Timeline day target.
            history:
                Current selected ancestry and attempts.

        Returns:
            Immutable injected-time write guard.
        """

        timeline, day, current_at = self._require_writable(target, history)
        return TimelineWriteGuard(
            timeline_id=timeline.id,
            day_id=day.id,
            expected_timeline_revision=timeline.revision,
            observed_at=current_at,
        )

    def resolve(
        self,
        scope: ConversationScope,
        source_message_id: UUID,
        mode: ContinuityMode,
    ) -> BranchModeFacts:
        """Resolve fail-closed Timeline branching facts after write validation.

        Args:
            scope:
                Exact conversation scope.
            source_message_id:
                Exact proposed persona branch point.
            mode:
                Requested continuity mode.

        Returns:
            Exact open-day fact, or missing facts when ownership contradicts.
        """

        facts = BranchModeFacts(
            scope=scope,
            source_message_id=source_message_id,
            mode=mode,
        )
        if mode != ContinuityMode.TIMELINE:
            return facts

        try:
            timeline = self._timelines.get(
                scope.identity_id, scope.persona_id, scope.continuity_id
            )
            latest = self._days.latest(timeline)
            graph = self._graphs.graph(scope)
        except (LookupError, ValueError):
            return facts

        source = next(
            (node for node in graph.nodes if node.id == source_message_id), None
        )
        if (
            latest is None
            or latest.scope != scope
            or source is None
            or source.role != "persona"
        ):
            return facts

        return facts.model_copy(update={"timeline_day_closed": latest.is_closed})

    def _require_writable(
        self, target: ConversationTarget, history: ConversationHistory
    ) -> tuple[Timeline, TimelineDay, datetime]:
        """Return exact open-day state and the instant used to authorize it.

        Args:
            target:
                Exact Timeline day target.
            history:
                Current selected ancestry and attempts.

        Returns:
            Timeline, day, and injected aware UTC observation.
        """

        timeline, day = self.inspect(target, history)
        if timeline.lifecycle != ContinuityLifecycle.ACTIVE:
            raise ArchivedContinuityError("Archived Timelines are read-only")

        latest = self._days.latest(timeline)
        if latest is None or latest.id != day.id:
            self._emit_rejection(
                timeline,
                day,
                TimelineGraphActionUnavailableReason.NOT_LATEST_DAY,
            )
            raise TimelineDayReadOnlyError(
                "Only the latest represented Timeline day can accept writes",
                TimelineGraphActionUnavailableReason.NOT_LATEST_DAY,
            )
        if day.is_closed:
            self._emit_rejection(
                timeline, day, TimelineGraphActionUnavailableReason.CLOSED_DAY
            )
            raise TimelineDayReadOnlyError(
                "Closed Timeline days are read-only",
                TimelineGraphActionUnavailableReason.CLOSED_DAY,
            )

        facts = self._calendar.resolve_current(self._clock, timeline.calendar_timezone)
        self._validate_clock(day, facts.current_at)
        if facts.current_at < day.boundary.closes_at:
            return timeline, day, facts.current_at

        selected = self._graphs.selected_path(day.scope)
        result = self._days.observe_closure(
            day.scope,
            day.id,
            facts.current_at,
            timeline.revision,
            selected.selected_leaf_id,
        )
        self._diagnostics.emit(
            CharactersDiagnostic(
                name=CharactersDiagnosticName.TIMELINE_CLOSURE,
                continuity_id=timeline.id,
                conversation_id=day.scope.conversation_id,
                entry_id=day.id,
                attempt_id=result.interrupted_attempt_id,
                mode=ContinuityMode.TIMELINE,
                local_date=day.boundary.local_date,
                boundary_timezone=day.boundary.timezone,
                policy="timeline_calendar",
                version="1.0.0",
                terminal_reason=result.status.value,
            )
        )
        if result.status == DayClosureStatus.STALE_REVISION:
            timeline = self._timelines.get(
                timeline.identity_id, timeline.persona_id, timeline.id
            )
            refreshed = self._days.get(day.scope, day.id)
            if timeline.lifecycle != ContinuityLifecycle.ACTIVE:
                raise ArchivedContinuityError("Archived Timelines are read-only")
            if refreshed.is_closed:
                self._emit_rejection(
                    timeline,
                    refreshed,
                    TimelineGraphActionUnavailableReason.CLOSED_DAY,
                )
                raise TimelineDayReadOnlyError(
                    "Closed Timeline days are read-only",
                    TimelineGraphActionUnavailableReason.CLOSED_DAY,
                )

            self._emit_rejection(
                timeline,
                refreshed,
                TimelineGraphActionUnavailableReason.MISSING_OR_CONTRADICTORY_FACTS,
            )
            raise TimelineDayReadOnlyError(
                "Timeline state changed while observing the day boundary",
                TimelineGraphActionUnavailableReason.MISSING_OR_CONTRADICTORY_FACTS,
            )

        self._emit_rejection(
            timeline, day, TimelineGraphActionUnavailableReason.CLOSED_DAY
        )
        raise TimelineDayReadOnlyError(
            "Closed Timeline days are read-only",
            TimelineGraphActionUnavailableReason.CLOSED_DAY,
        )

    def _validate_clock(self, day: TimelineDay, current_at: datetime) -> None:
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
            self._diagnostics.emit(
                CharactersDiagnostic(
                    name=CharactersDiagnosticName.TIMELINE_HISTORICAL_REJECTION,
                    continuity_id=day.entry.continuity_id,
                    conversation_id=day.scope.conversation_id,
                    entry_id=day.id,
                    mode=ContinuityMode.TIMELINE,
                    local_date=day.boundary.local_date,
                    boundary_timezone=day.boundary.timezone,
                    policy="timeline_calendar",
                    version="1.0.0",
                    terminal_reason=(
                        TimelineGraphActionUnavailableReason.MISSING_OR_CONTRADICTORY_FACTS.value
                    ),
                )
            )
            raise TimelineDayReadOnlyError(
                "The clock predates committed Timeline day facts",
                TimelineGraphActionUnavailableReason.MISSING_OR_CONTRADICTORY_FACTS,
            )

    def _emit_rejection(
        self,
        timeline: Timeline,
        day: TimelineDay,
        reason: TimelineGraphActionUnavailableReason,
    ) -> None:
        """Emit one content-free rejected Timeline operation.

        Args:
            timeline:
                Owning Timeline snapshot.
            day:
                Exact rejected represented day.
            reason:
                Stable read-only policy reason.
        """

        self._diagnostics.emit(
            CharactersDiagnostic(
                name=CharactersDiagnosticName.TIMELINE_HISTORICAL_REJECTION,
                continuity_id=timeline.id,
                conversation_id=day.scope.conversation_id,
                entry_id=day.id,
                mode=ContinuityMode.TIMELINE,
                local_date=day.boundary.local_date,
                boundary_timezone=day.boundary.timezone,
                policy="timeline_graph_actions",
                version="1.0.0",
                terminal_reason=reason.value,
            )
        )
