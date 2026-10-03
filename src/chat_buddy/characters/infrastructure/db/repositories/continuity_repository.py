"""Transactional first use, persisted confirmation, and continuity isolation."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    ActiveContinuityError,
    ConfirmationConflictError,
    Continuity,
    ContinuityLifecycle,
    ContinuityMode,
    ContinuityNotFoundError,
    IdentityNotFoundError,
    PersonaNotFoundError,
    StaleIdentityError,
    StalePersonaError,
    StartContinuity,
    StartingRelationship,
    UnsupportedContinuityModeError,
)
from chat_buddy.characters.infrastructure.db.models import (
    ContinuityModel,
    ConversationModel,
    IdentityModel,
    PersonaModel,
    StartingRelationshipModel,
)


class DbContinuityRepository:
    """Own transactions spanning Characters profiles and continuity records."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Bind isolated Characters transactions.

        Args:
            session_factory:
                Characters-owned database session factory.
        """

        self._session_factory = session_factory

    def start(
        self, request: StartContinuity, relationship: StartingRelationship
    ) -> Continuity:
        """Serialize first use with edits and commit every start record together.

        Args:
            request:
                Complete confirmed request including reviewed revisions.
            relationship:
                Resolved initial values and origins.

        Returns:
            New continuity or the identical confirmation's original snapshot.

        Raises:
            ActiveContinuityError:
                If this pair already owns an active Ongoing.
            ConfirmationConflictError:
                If this confirmation belongs to different submitted data.
            IdentityNotFoundError:
                If the selected identity is missing.
            PersonaNotFoundError:
                If the selected persona is missing.
            StaleIdentityError:
                If the reviewed identity revision changed.
            StalePersonaError:
                If the reviewed persona revision changed.
            UnsupportedContinuityModeError:
                If a reserved mode is requested.
        """

        if request.mode != ContinuityMode.ONGOING:
            raise UnsupportedContinuityModeError("Only Ongoing is available")

        try:
            with self._session_factory() as session, session.begin():
                existing = self._confirmation(session, request)
                if existing is not None:
                    return self._snapshot(session, existing)

                # Conditional profile edits acquire these same row locks. Always
                # lock identity first, then persona, even when already frozen.
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

                # A concurrent identical start may have committed while locking.
                existing = self._confirmation(session, request)
                if existing is not None:
                    return self._snapshot(session, existing)

                if identity.revision != request.identity_revision:
                    raise StaleIdentityError(
                        "Review the current identity before starting"
                    )
                if persona.revision != request.persona_revision:
                    raise StalePersonaError(
                        "Review the current persona before starting"
                    )
                if self._active(session, request) is not None:
                    raise ActiveContinuityError(
                        "Archive the active Ongoing before starting a replacement"
                    )

                identity.is_frozen = True
                persona.is_frozen = True
                row = ContinuityModel(
                    identity_id=identity.id,
                    persona_id=persona.id,
                    mode=request.mode.value,
                    lifecycle=ContinuityLifecycle.ACTIVE.value,
                    request_id=request.request_id,
                    confirmed_request=request.model_dump(mode="json"),
                )

                session.add(row)
                session.flush()
                session.add_all(
                    [
                        ConversationModel(
                            continuity_id=row.id,
                            identity_id=row.identity_id,
                            persona_id=row.persona_id,
                        ),
                        StartingRelationshipModel(
                            continuity_id=row.id,
                            identity_id=row.identity_id,
                            persona_id=row.persona_id,
                            snapshot=relationship.model_dump(mode="json"),
                        ),
                    ]
                )
                session.flush()
                return self._snapshot(session, row)
        except IntegrityError:
            # Different pairs need not share row locks. A confirmation collision
            # still resolves only after rolling back the entire losing start.
            with self._session_factory() as session:
                existing = self._confirmation(session, request)
                if existing is not None:
                    return self._snapshot(session, existing)
                if self._active(session, request) is not None:
                    raise ActiveContinuityError(
                        "An active Ongoing already exists"
                    ) from None
            raise

    def find_confirmation(self, request: StartContinuity) -> Continuity | None:
        """Resolve a persisted confirmation without requiring a profile revision.

        Args:
            request:
                Complete confirmed request.

        Returns:
            Original continuity, or None for a new confirmation.

        Raises:
            ConfirmationConflictError:
                If submitted data differs from the persisted confirmation.
        """

        with self._session_factory() as session:
            row = self._confirmation(session, request)
            return None if row is None else self._snapshot(session, row)

    def find_active(self, identity_id: UUID, persona_id: UUID) -> Continuity | None:
        """Read the pair's active Ongoing for application preflight checks.

        Args:
            identity_id:
                Selected identity owner.
            persona_id:
                Selected persona owner.

        Returns:
            Active Ongoing snapshot, or None when no active Ongoing exists.
        """

        with self._session_factory() as session:
            row = session.scalar(
                select(ContinuityModel).where(
                    ContinuityModel.identity_id == identity_id,
                    ContinuityModel.persona_id == persona_id,
                    ContinuityModel.mode == "ongoing",
                    ContinuityModel.lifecycle == "active",
                )
            )
            return None if row is None else self._snapshot(session, row)

    def get(
        self, identity_id: UUID, persona_id: UUID, continuity_id: UUID
    ) -> Continuity:
        """Read active or archived records under explicit ownership.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            continuity_id:
                Continuity identifier.

        Returns:
            Detached continuity snapshot.

        Raises:
            ContinuityNotFoundError:
                If the continuity does not belong to the supplied pair.
        """

        with self._session_factory() as session:
            row = self._owned(session, identity_id, persona_id, continuity_id)
            return self._snapshot(session, row)

    def list(self) -> list[Continuity]:
        """Read deterministic identity/persona groups including archives.

        Returns:
            Snapshots ordered by identity, persona, and continuity UUID.
        """

        with self._session_factory() as session:
            rows = session.scalars(
                select(ContinuityModel).order_by(
                    ContinuityModel.identity_id,
                    ContinuityModel.persona_id,
                    ContinuityModel.id,
                )
            )
            return [self._snapshot(session, row) for row in rows]

    def archive(
        self, identity_id: UUID, persona_id: UUID, continuity_id: UUID
    ) -> Continuity:
        """Serialize archival on the continuity row used by future message writes.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            continuity_id:
                Continuity identifier.

        Returns:
            Archived snapshot, including repeated archive requests.

        Raises:
            ContinuityNotFoundError:
                If the continuity does not belong to the supplied pair.
        """

        with self._session_factory() as session, session.begin():
            row = self._owned(
                session, identity_id, persona_id, continuity_id, lock=True
            )
            row.lifecycle = ContinuityLifecycle.ARCHIVED.value
            session.flush()
            return self._snapshot(session, row)

    @staticmethod
    def _owned(
        session: Session,
        identity_id: UUID,
        persona_id: UUID,
        continuity_id: UUID,
        lock: bool = False,
    ) -> ContinuityModel:
        """Select a continuity without leaking another pair's records.

        Args:
            session:
                Current repository session.
            identity_id:
                Required identity binding.
            persona_id:
                Required persona binding.
            continuity_id:
                Requested continuity.
            lock:
                Whether to serialize a lifecycle mutation.

        Returns:
            The matching persistence row.

        Raises:
            ContinuityNotFoundError:
                If ownership does not match.
        """

        query = select(ContinuityModel).where(
            ContinuityModel.id == continuity_id,
            ContinuityModel.identity_id == identity_id,
            ContinuityModel.persona_id == persona_id,
        )
        row = session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise ContinuityNotFoundError(str(continuity_id))
        return row

    @staticmethod
    def _confirmation(
        session: Session, request: StartContinuity
    ) -> ContinuityModel | None:
        """Resolve persisted confirmation equality before any revision checks.

        Args:
            session:
                Current repository session.
            request:
                Complete confirmed request.

        Returns:
            Original row for identical submission, otherwise no row.

        Raises:
            ConfirmationConflictError:
                If submitted data differs from the persisted confirmation.
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
    def _active(session: Session, request: StartContinuity) -> ContinuityModel | None:
        """Find an active Ongoing for the submitted pair.

        Args:
            session:
                Current repository session.
            request:
                Pair being started.

        Returns:
            Conflicting active row, if any.
        """

        return session.scalar(
            select(ContinuityModel).where(
                ContinuityModel.identity_id == request.identity_id,
                ContinuityModel.persona_id == request.persona_id,
                ContinuityModel.mode == "ongoing",
                ContinuityModel.lifecycle == "active",
            )
        )

    @staticmethod
    def _snapshot(session: Session, row: ContinuityModel) -> Continuity:
        """Read child records only within the continuity's complete ownership.

        Args:
            session:
                Current repository session.
            row:
                Owned continuity row.

        Returns:
            Immutable complete domain snapshot.
        """

        conversation = session.scalars(
            select(ConversationModel).where(
                ConversationModel.continuity_id == row.id,
                ConversationModel.identity_id == row.identity_id,
                ConversationModel.persona_id == row.persona_id,
            )
        ).one()
        state = session.scalars(
            select(StartingRelationshipModel).where(
                StartingRelationshipModel.continuity_id == row.id,
                StartingRelationshipModel.identity_id == row.identity_id,
                StartingRelationshipModel.persona_id == row.persona_id,
            )
        ).one()

        return Continuity(
            id=row.id,
            identity_id=row.identity_id,
            persona_id=row.persona_id,
            mode=ContinuityMode(row.mode),
            lifecycle=ContinuityLifecycle(row.lifecycle),
            conversation_id=conversation.id,
            relationship=StartingRelationship.model_validate(state.snapshot),
        )
