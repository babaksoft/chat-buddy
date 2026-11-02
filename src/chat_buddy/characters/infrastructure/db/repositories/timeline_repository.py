"""Transactional persistence for Timeline ownership and lifecycle."""

from itertools import groupby
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    ApplicationLocalTimezone,
    ConfirmationConflictError,
    ContinuityLifecycle,
    ContinuityNotFoundError,
    IdentityNotFoundError,
    PersonaNotFoundError,
    StaleIdentityError,
    StalePersonaError,
    StartingRelationship,
    StartTimeline,
    Timeline,
    TimelineGroup,
    TimelineRevisionResult,
    TimelineRevisionStatus,
    TimelineStartResult,
    TimelineStartStatus,
    VersionedResponseStyleSettings,
)
from chat_buddy.characters.infrastructure.db.models import (
    ContinuityModel,
    IdentityModel,
    PersonaModel,
    ResponseStyleSettingsModel,
    StartingRelationshipModel,
    TimelineModel,
)


class DbTimelineRepository:
    """Persist Timeline ownership, immutable timezone, and lifecycle."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory:
                Factory used for short database transactions.
        """

        self._factory = session_factory

    def start(
        self, request: StartTimeline, relationship: StartingRelationship
    ) -> TimelineStartResult:
        """Atomically start a Timeline without creating a represented day.

        Args:
            request:
                Complete reviewed confirmation.
            relationship:
                Resolved starting relationship.

        Returns:
            Explicit start, idempotent, or active-slot-conflict result.
        """

        try:
            with self._factory() as session, session.begin():
                existing = self._confirmation(session, request)
                if existing is not None:
                    return self._start_snapshot(
                        session, existing, TimelineStartStatus.IDEMPOTENT
                    )
                identity = session.scalar(
                    select(IdentityModel)
                    .where(IdentityModel.id == request.identity_id)
                    .with_for_update()
                )
                if identity is None:
                    raise IdentityNotFoundError(str(request.identity_id))
                persona = session.scalar(
                    select(PersonaModel)
                    .where(PersonaModel.id == request.persona_id)
                    .with_for_update()
                )
                if persona is None:
                    raise PersonaNotFoundError(str(request.persona_id))
                if identity.revision != request.identity_revision:
                    raise StaleIdentityError(
                        "Review the current identity before starting"
                    )
                if persona.revision != request.persona_revision:
                    raise StalePersonaError(
                        "Review the current persona before starting"
                    )
                if self._active(session, request.identity_id, request.persona_id):
                    return TimelineStartResult(
                        status=TimelineStartStatus.ACTIVE_SLOT_CONFLICT,
                        timeline=None,
                        style=None,
                    )

                identity.is_frozen = True
                persona.is_frozen = True
                continuity = ContinuityModel(
                    identity_id=identity.id,
                    persona_id=persona.id,
                    mode="timeline",
                    lifecycle="active",
                    request_id=request.request_id,
                    confirmed_request=request.model_dump(mode="json"),
                )
                session.add(continuity)
                session.flush()
                settings = request.response_style
                session.add_all(
                    [
                        TimelineModel(
                            continuity_id=continuity.id,
                            identity_id=identity.id,
                            persona_id=persona.id,
                            mode="timeline",
                            name=request.name,
                            calendar_timezone=request.calendar_timezone.name,
                            revision=1,
                        ),
                        StartingRelationshipModel(
                            continuity_id=continuity.id,
                            identity_id=identity.id,
                            persona_id=persona.id,
                            snapshot=relationship.model_dump(mode="json"),
                        ),
                        ResponseStyleSettingsModel(
                            continuity_id=continuity.id,
                            identity_id=identity.id,
                            persona_id=persona.id,
                            scene_description=settings.scene_description.value,
                            response_length=settings.response_length.value,
                            narrative_placement=settings.narrative_placement.value,
                            revision=1,
                        ),
                    ]
                )
                session.flush()
                return self._start_snapshot(
                    session, continuity, TimelineStartStatus.STARTED
                )
        except IntegrityError:
            with self._factory() as session:
                existing = self._confirmation(session, request)
                if existing is not None:
                    return self._start_snapshot(
                        session, existing, TimelineStartStatus.IDEMPOTENT
                    )
                if self._active(session, request.identity_id, request.persona_id):
                    return TimelineStartResult(
                        status=TimelineStartStatus.ACTIVE_SLOT_CONFLICT,
                        timeline=None,
                        style=None,
                    )
            raise

    def find_confirmation(self, request: StartTimeline) -> TimelineStartResult | None:
        """Find an identical prior confirmation.

        Args:
            request:
                Complete reviewed confirmation.

        Returns:
            Idempotent prior result, or None.
        """

        with self._factory() as session:
            row = self._confirmation(session, request)
            return (
                None
                if row is None
                else self._start_snapshot(session, row, TimelineStartStatus.IDEMPOTENT)
            )

    def find_active(self, identity_id: UUID, persona_id: UUID) -> Timeline | None:
        """Find the pair's active Timeline.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.

        Returns:
            Active Timeline or None.
        """

        with self._factory() as session:
            row = self._active(session, identity_id, persona_id)
            return None if row is None else self._snapshot(session, row)

    def get(self, identity_id: UUID, persona_id: UUID, timeline_id: UUID) -> Timeline:
        """Read a Timeline under complete ownership.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            timeline_id:
                Timeline identifier.

        Returns:
            Detached Timeline snapshot.
        """

        with self._factory() as session:
            return self._snapshot(
                session, self._owned(session, identity_id, persona_id, timeline_id)
            )

    def list(self) -> tuple[TimelineGroup, ...]:
        """List all Timelines grouped deterministically by profile pair.

        Returns:
            Validated Timeline groups.
        """

        with self._factory() as session:
            rows = tuple(
                session.scalars(
                    select(TimelineModel).order_by(
                        TimelineModel.identity_id,
                        TimelineModel.persona_id,
                        TimelineModel.continuity_id,
                    )
                )
            )
            return tuple(
                TimelineGroup(
                    identity_id=key[0],
                    persona_id=key[1],
                    timelines=tuple(self._snapshot(session, row) for row in group),
                )
                for key, group in groupby(
                    rows, key=lambda row: (row.identity_id, row.persona_id)
                )
            )

    def list_for_pair(self, identity_id: UUID, persona_id: UUID) -> TimelineGroup:
        """List a pair's Timelines in stable identifier order.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.

        Returns:
            Validated pair group.
        """

        with self._factory() as session:
            rows = session.scalars(
                select(TimelineModel)
                .where(
                    TimelineModel.identity_id == identity_id,
                    TimelineModel.persona_id == persona_id,
                )
                .order_by(TimelineModel.continuity_id)
            )
            return TimelineGroup(
                identity_id=identity_id,
                persona_id=persona_id,
                timelines=tuple(self._snapshot(session, row) for row in rows),
            )

    def revise(
        self,
        identity_id: UUID,
        persona_id: UUID,
        timeline_id: UUID,
        name: str,
        expected_revision: int,
    ) -> TimelineRevisionResult:
        """Replace Timeline presentation metadata under an optimistic guard.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            timeline_id:
                Timeline identifier.
            name:
                Validated replacement name.
            expected_revision:
                Last observed revision.

        Returns:
            Explicit revision result.
        """

        with self._factory() as session, session.begin():
            row = self._owned(session, identity_id, persona_id, timeline_id, lock=True)
            continuity = self._continuity(session, row, lock=True)
            current = self._snapshot(session, row)
            if continuity.lifecycle != "active":
                return TimelineRevisionResult(
                    status=TimelineRevisionStatus.ARCHIVED, timeline=current
                )
            if row.revision != expected_revision:
                return TimelineRevisionResult(
                    status=TimelineRevisionStatus.STALE_REVISION, timeline=current
                )
            validated = Timeline.model_validate(
                current.model_copy(update={"name": name}).model_dump()
            )
            if validated.name == row.name:
                return TimelineRevisionResult(
                    status=TimelineRevisionStatus.IDEMPOTENT, timeline=current
                )
            row.name = validated.name
            row.revision += 1
            session.flush()

            return TimelineRevisionResult(
                status=TimelineRevisionStatus.UPDATED,
                timeline=self._snapshot(session, row),
            )

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
                Timeline identifier.
            expected_revision:
                Last observed revision.

        Returns:
            Explicit archive result.
        """

        with self._factory() as session, session.begin():
            row = self._owned(session, identity_id, persona_id, timeline_id, lock=True)
            continuity = self._continuity(session, row, lock=True)
            current = self._snapshot(session, row)
            if continuity.lifecycle == "archived":
                return TimelineRevisionResult(
                    status=TimelineRevisionStatus.IDEMPOTENT, timeline=current
                )
            if row.revision != expected_revision:
                return TimelineRevisionResult(
                    status=TimelineRevisionStatus.STALE_REVISION, timeline=current
                )
            continuity.lifecycle = "archived"
            row.revision += 1
            session.flush()
            return TimelineRevisionResult(
                status=TimelineRevisionStatus.UPDATED,
                timeline=self._snapshot(session, row),
            )

    @staticmethod
    def _confirmation(
        session: Session, request: StartTimeline
    ) -> ContinuityModel | None:
        """Resolve exact confirmation equality.

        Args:
            session:
                Current session.
            request:
                Submitted confirmation.

        Returns:
            Existing continuity or None.
        """

        row = session.scalar(
            select(ContinuityModel).where(
                ContinuityModel.request_id == request.request_id
            )
        )
        if row is not None and row.confirmed_request != request.model_dump(mode="json"):
            raise ConfirmationConflictError(
                "Use a new confirmation identifier for changed inputs"
            )

        return row

    @staticmethod
    def _active(
        session: Session, identity_id: UUID, persona_id: UUID
    ) -> TimelineModel | None:
        """Find an active Timeline row.

        Args:
            session:
                Current session.
            identity_id:
                Identity owner.
            persona_id:
                Persona owner.

        Returns:
            Active row or None.
        """

        return session.scalar(
            select(TimelineModel)
            .join(ContinuityModel, ContinuityModel.id == TimelineModel.continuity_id)
            .where(
                TimelineModel.identity_id == identity_id,
                TimelineModel.persona_id == persona_id,
                ContinuityModel.lifecycle == "active",
            )
        )

    @staticmethod
    def _owned(
        session: Session,
        identity_id: UUID,
        persona_id: UUID,
        timeline_id: UUID,
        lock: bool = False,
    ) -> TimelineModel:
        """Load an exactly owned Timeline row.

        Args:
            session:
                Current session.
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            timeline_id:
                Expected Timeline identifier.
            lock:
                Whether to lock the row.

        Returns:
            Owned Timeline row.
        """

        query = select(TimelineModel).where(
            TimelineModel.continuity_id == timeline_id,
            TimelineModel.identity_id == identity_id,
            TimelineModel.persona_id == persona_id,
            TimelineModel.mode == "timeline",
        )
        row = session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise ContinuityNotFoundError(str(timeline_id))

        return row

    @staticmethod
    def _continuity(
        session: Session, row: TimelineModel, lock: bool = False
    ) -> ContinuityModel:
        """Load the exact owning continuity.

        Args:
            session:
                Current session.
            row:
                Owned Timeline row.
            lock:
                Whether to lock lifecycle state.

        Returns:
            Exact continuity row.
        """

        query = select(ContinuityModel).where(
            ContinuityModel.id == row.continuity_id,
            ContinuityModel.identity_id == row.identity_id,
            ContinuityModel.persona_id == row.persona_id,
            ContinuityModel.mode == "timeline",
        )

        return session.scalars(query.with_for_update() if lock else query).one()

    @classmethod
    def _snapshot(cls, session: Session, row: TimelineModel) -> Timeline:
        """Build an immutable Timeline snapshot.

        Args:
            session:
                Current session.
            row:
                Timeline persistence row.

        Returns:
            Validated detached Timeline.
        """

        continuity = cls._continuity(session, row)
        relationship = session.scalars(
            select(StartingRelationshipModel).where(
                StartingRelationshipModel.continuity_id == row.continuity_id
            )
        ).one()

        return Timeline(
            id=row.continuity_id,
            identity_id=row.identity_id,
            persona_id=row.persona_id,
            name=row.name,
            lifecycle=ContinuityLifecycle(continuity.lifecycle),
            relationship=StartingRelationship.model_validate(relationship.snapshot),
            calendar_timezone=ApplicationLocalTimezone(name=row.calendar_timezone),
            revision=row.revision,
        )

    @classmethod
    def _start_snapshot(
        cls, session: Session, continuity: ContinuityModel, status: TimelineStartStatus
    ) -> TimelineStartResult:
        """Build an exact persisted start result.

        Args:
            session:
                Current session.
            continuity:
                Confirmed Timeline continuity.
            status:
                Start outcome to report.

        Returns:
            Detached start result.
        """

        row = session.scalars(
            select(TimelineModel).where(TimelineModel.continuity_id == continuity.id)
        ).one()
        style_row = session.scalars(
            select(ResponseStyleSettingsModel).where(
                ResponseStyleSettingsModel.continuity_id == continuity.id
            )
        ).one()
        settings = StartTimeline.model_validate(
            continuity.confirmed_request
        ).response_style

        return TimelineStartResult(
            status=status,
            timeline=cls._snapshot(session, row),
            style=VersionedResponseStyleSettings(
                settings=settings, revision=style_row.revision
            ),
        )
