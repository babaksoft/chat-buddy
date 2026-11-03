"""Persistence for represented Timeline days and first interactions."""

from datetime import UTC, date, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import ResponseStyleRenderer
from chat_buddy.characters.domain import (
    AttemptStatus,
    ConversationScope,
    DayBoundary,
    DayClosureResult,
    DayClosureStatus,
    DayReservationResult,
    DayReservationStatus,
    EffectiveGeneration,
    GenerationAttempt,
    Message,
    NarrativePlacement,
    ReserveTimelineDay,
    ResponseLength,
    ResponseStyleSettings,
    SceneDescriptionLevel,
    Timeline,
    TimelineDay,
    TimelineNavigation,
    VersionedResponseStyleSettings,
)
from chat_buddy.characters.infrastructure.db.models import (
    ContinuityModel,
    ConversationModel,
    GenerationAttemptModel,
    MessageModel,
    ResponseStyleSettingsModel,
    TimelineDayModel,
    TimelineModel,
)


class DbTimelineDayRepository:
    """Persist immutable days and serialize calendar writes on a Timeline."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory:
                Factory used for short database transactions.
        """

        self._factory = session_factory

    def get(self, scope: ConversationScope, day_id: UUID) -> TimelineDay:
        """Read one day under complete conversation ownership.

        Args:
            scope:
                Expected ownership.
            day_id:
                Represented-day identifier.

        Returns:
            Detached represented day.
        """

        with self._factory() as session:
            row = session.scalar(
                select(TimelineDayModel).where(
                    TimelineDayModel.id == day_id,
                    TimelineDayModel.continuity_id == scope.continuity_id,
                    TimelineDayModel.identity_id == scope.identity_id,
                    TimelineDayModel.persona_id == scope.persona_id,
                    TimelineDayModel.conversation_id == scope.conversation_id,
                )
            )
            if row is None:
                raise ValueError("Timeline day ownership does not match")

            return self._snapshot(row)

    def find_date(self, timeline: Timeline, local_date: date) -> TimelineDay | None:
        """Find one represented date in a Timeline.

        Args:
            timeline:
                Expected owning Timeline.
            local_date:
                Immutable local date.

        Returns:
            Existing represented day or None.
        """

        with self._factory() as session:
            row = session.scalar(
                select(TimelineDayModel).where(
                    TimelineDayModel.continuity_id == timeline.id,
                    TimelineDayModel.identity_id == timeline.identity_id,
                    TimelineDayModel.persona_id == timeline.persona_id,
                    TimelineDayModel.local_date == local_date,
                )
            )

            return None if row is None else self._snapshot(row)

    def latest(self, timeline: Timeline) -> TimelineDay | None:
        """Load the latest represented day.

        Args:
            timeline:
                Expected owning Timeline.

        Returns:
            Latest day or None.
        """

        with self._factory() as session:
            row = session.scalar(
                select(TimelineDayModel)
                .where(TimelineDayModel.continuity_id == timeline.id)
                .order_by(TimelineDayModel.position.desc())
                .limit(1)
            )

            return None if row is None else self._snapshot(row)

    def list(self, timeline: Timeline) -> TimelineNavigation:
        """List all represented days in immutable order.

        Args:
            timeline:
                Expected owning Timeline.

        Returns:
            Validated navigation snapshot.
        """

        with self._factory() as session:
            rows = session.scalars(
                select(TimelineDayModel)
                .where(TimelineDayModel.continuity_id == timeline.id)
                .order_by(TimelineDayModel.position)
            )

            return TimelineNavigation(
                timeline=timeline, days=tuple(self._snapshot(row) for row in rows)
            )

    def reserve_first(
        self, timeline: Timeline, request: ReserveTimelineDay
    ) -> DayReservationResult:
        """Atomically create a day, first user node, and pending attempt.

        Args:
            timeline:
                Last observed Timeline snapshot.
            request:
                Boundary and reservation guards.

        Returns:
            Explicit reservation or conflict result.
        """

        if request.timeline_id != timeline.id:
            raise ValueError("Day reservation must target the supplied Timeline")
        if request.boundary.timezone != timeline.calendar_timezone.name:
            raise ValueError("Day boundary must use the captured Timeline timezone")

        try:
            with self._factory() as session, session.begin():
                owner = session.scalar(
                    select(TimelineModel)
                    .where(
                        TimelineModel.continuity_id == timeline.id,
                        TimelineModel.identity_id == timeline.identity_id,
                        TimelineModel.persona_id == timeline.persona_id,
                    )
                    .with_for_update()
                )
                if owner is None:
                    raise ValueError("Timeline ownership does not match")
                continuity = session.scalars(
                    select(ContinuityModel)
                    .where(ContinuityModel.id == timeline.id)
                    .with_for_update()
                ).one()
                if continuity.lifecycle != "active":
                    return self._failed(DayReservationStatus.ARCHIVED)
                if owner.revision != request.expected_timeline_revision:
                    return self._failed(DayReservationStatus.STALE_REVISION)
                latest = session.scalar(
                    select(TimelineDayModel)
                    .where(TimelineDayModel.continuity_id == timeline.id)
                    .order_by(TimelineDayModel.position.desc())
                    .limit(1)
                )
                if latest is not None:
                    selected = session.scalar(
                        select(ConversationModel.selected_leaf_id).where(
                            ConversationModel.id == latest.conversation_id
                        )
                    )
                    if latest.closed_at is None:
                        return self._failed(DayReservationStatus.DAY_CLOSED)
                    if selected != request.expected_selected_leaf_id:
                        return self._failed(DayReservationStatus.STALE_LEAF)
                    if latest.local_date == request.boundary.local_date:
                        return self._failed(DayReservationStatus.DUPLICATE_DATE)
                    if latest.local_date > request.boundary.local_date:
                        return self._failed(DayReservationStatus.STALE_REVISION)
                elif request.expected_selected_leaf_id is not None:
                    return self._failed(DayReservationStatus.STALE_LEAF)

                conversation = ConversationModel(
                    continuity_id=timeline.id,
                    identity_id=timeline.identity_id,
                    persona_id=timeline.persona_id,
                    mode="timeline",
                )
                session.add(conversation)
                session.flush()
                day = TimelineDayModel(
                    continuity_id=timeline.id,
                    identity_id=timeline.identity_id,
                    persona_id=timeline.persona_id,
                    conversation_id=conversation.id,
                    mode="timeline",
                    position=1 if latest is None else latest.position + 1,
                    local_date=request.boundary.local_date,
                    boundary_timezone=request.boundary.timezone,
                    opens_at=request.boundary.opens_at,
                    closes_at=request.boundary.closes_at,
                )
                now = datetime.now(UTC)
                message = MessageModel(
                    conversation_id=conversation.id,
                    continuity_id=timeline.id,
                    role="user",
                    content=request.submitted_input.content,
                    parent_id=None,
                    created_at=now,
                )
                session.add_all([day, message])
                session.flush()
                conversation.selected_leaf_id = message.id
                style = self._effective_style(session, timeline.id)
                attempt = GenerationAttemptModel(
                    conversation_id=conversation.id,
                    continuity_id=timeline.id,
                    user_message_id=message.id,
                    selection_guard_id=message.id,
                    submitted_input=message.content,
                    generation=request.generation.model_dump(mode="json"),
                    response_style=style,
                    status="pending",
                    incomplete_output="",
                    created_at=now,
                    updated_at=now,
                )
                session.add(attempt)
                owner.revision += 1
                session.flush()
                scope = ConversationScope(
                    identity_id=timeline.identity_id,
                    persona_id=timeline.persona_id,
                    continuity_id=timeline.id,
                    conversation_id=conversation.id,
                )
                return DayReservationResult(
                    status=DayReservationStatus.RESERVED,
                    day=self._snapshot(day),
                    user_message=Message(
                        id=message.id,
                        scope=scope,
                        sequence=1,
                        role="user",
                        content=message.content,
                        created_at=self._utc(message.created_at),
                    ),
                    attempt=self._attempt(scope, attempt),
                )
        except IntegrityError:
            return self._failed(DayReservationStatus.DUPLICATE_DATE)

    def observe_closure(
        self,
        scope: ConversationScope,
        day_id: UUID,
        observed_at: datetime,
        expected_timeline_revision: int,
        expected_selected_leaf_id: UUID | None,
    ) -> DayClosureResult:
        """Observe and idempotently persist day closure under graph guards.

        Args:
            scope:
                Complete expected ownership.
            day_id:
                Represented day identifier.
            observed_at:
                Injected aware UTC observation instant.
            expected_timeline_revision:
                Last observed Timeline revision.
            expected_selected_leaf_id:
                Last observed selected graph leaf.

        Returns:
            Explicit closure result.
        """

        if observed_at.tzinfo is None or observed_at.utcoffset() != UTC.utcoffset(
            observed_at
        ):
            raise ValueError("Closure observation must be aware UTC")
        with self._factory() as session, session.begin():
            owner = session.scalars(
                select(TimelineModel)
                .where(TimelineModel.continuity_id == scope.continuity_id)
                .with_for_update()
            ).one()
            day = session.scalars(
                select(TimelineDayModel)
                .where(
                    TimelineDayModel.id == day_id,
                    TimelineDayModel.continuity_id == scope.continuity_id,
                    TimelineDayModel.conversation_id == scope.conversation_id,
                    TimelineDayModel.identity_id == scope.identity_id,
                    TimelineDayModel.persona_id == scope.persona_id,
                )
                .with_for_update()
            ).one()
            if day.closed_at is not None:
                return DayClosureResult(
                    status=DayClosureStatus.ALREADY_CLOSED, day=self._snapshot(day)
                )
            if owner.revision != expected_timeline_revision:
                return DayClosureResult(
                    status=DayClosureStatus.STALE_REVISION, day=self._snapshot(day)
                )
            if observed_at < self._utc(day.closes_at):
                return DayClosureResult(
                    status=DayClosureStatus.STILL_OPEN, day=self._snapshot(day)
                )
            conversation = session.scalars(
                select(ConversationModel)
                .where(ConversationModel.id == scope.conversation_id)
                .with_for_update()
            ).one()
            if conversation.selected_leaf_id is None:
                raise ValueError("A represented day must have a selected leaf")
            raced = conversation.selected_leaf_id != expected_selected_leaf_id
            attempt = session.scalar(
                select(GenerationAttemptModel).where(
                    GenerationAttemptModel.conversation_id == scope.conversation_id,
                    GenerationAttemptModel.status.in_(["pending", "streaming"]),
                )
            )
            interrupted_id = None
            if attempt is not None:
                interrupted_id = attempt.id
                attempt.status = "interrupted"
                attempt.updated_at = attempt.finished_at = observed_at
            day.closed_at = observed_at
            day.settled_selected_leaf_id = conversation.selected_leaf_id
            owner.revision += 1
            session.flush()
            return DayClosureResult(
                status=(
                    DayClosureStatus.CLOSURE_RACE if raced else DayClosureStatus.CLOSED
                ),
                day=self._snapshot(day),
                interrupted_attempt_id=interrupted_id,
            )

    @staticmethod
    def _failed(status: DayReservationStatus) -> DayReservationResult:
        """Build a payload-free failed reservation.

        Args:
            status:
                Explicit failure status.

        Returns:
            Validated result without partial writes.
        """

        return DayReservationResult(
            status=status, day=None, user_message=None, attempt=None
        )

    @staticmethod
    def _effective_style(session: Session, continuity_id: UUID) -> dict[str, object]:
        """Render the current style row for attempt provenance.

        Args:
            session:
                Current reservation transaction.
            continuity_id:
                Owning continuity.

        Returns:
            JSON-ready effective style snapshot.
        """

        row = session.scalars(
            select(ResponseStyleSettingsModel)
            .where(ResponseStyleSettingsModel.continuity_id == continuity_id)
            .with_for_update()
        ).one()
        current = VersionedResponseStyleSettings(
            settings=ResponseStyleSettings(
                scene_description=SceneDescriptionLevel(row.scene_description),
                response_length=ResponseLength(row.response_length),
                narrative_placement=NarrativePlacement(row.narrative_placement),
            ),
            revision=row.revision,
        )

        return ResponseStyleRenderer().render(current).model_dump(mode="json")

    @classmethod
    def _snapshot(cls, row: TimelineDayModel) -> TimelineDay:
        """Build an immutable represented-day snapshot.

        Args:
            row:
                Persistence row.

        Returns:
            Validated detached day.
        """

        return TimelineDay(
            id=row.id,
            scope=ConversationScope(
                identity_id=row.identity_id,
                persona_id=row.persona_id,
                continuity_id=row.continuity_id,
                conversation_id=row.conversation_id,
            ),
            position=row.position,
            boundary=DayBoundary(
                local_date=row.local_date,
                timezone=row.boundary_timezone,
                opens_at=cls._utc(row.opens_at),
                closes_at=cls._utc(row.closes_at),
            ),
            closed_at=None if row.closed_at is None else cls._utc(row.closed_at),
            settled_selected_leaf_id=row.settled_selected_leaf_id,
        )

    @classmethod
    def _attempt(
        cls, scope: ConversationScope, row: GenerationAttemptModel
    ) -> GenerationAttempt:
        """Build a detached attempt snapshot.

        Args:
            scope:
                Complete conversation ownership.
            row:
                Attempt persistence row.

        Returns:
            Validated pending attempt.
        """

        return GenerationAttempt(
            id=row.id,
            scope=scope,
            user_message_id=row.user_message_id,
            submitted_input=row.submitted_input,
            generation=EffectiveGeneration.model_validate(row.generation),
            status=cast(AttemptStatus, row.status),
            incomplete_output=row.incomplete_output,
            created_at=cls._utc(row.created_at),
            updated_at=cls._utc(row.updated_at),
            finished_at=None if row.finished_at is None else cls._utc(row.finished_at),
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        """Normalize PostgreSQL or SQLite timestamps to aware UTC.

        Args:
            value:
                Persisted timestamp.

        Returns:
            Aware UTC timestamp.
        """

        return (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        )
