"""Transactional persistence for named Storylines and ordered scenes."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    ActiveStorylineError,
    ArchivedContinuityError,
    ConfirmationConflictError,
    ContinuityLifecycle,
    ContinuityNotFoundError,
    ConversationScope,
    IdentityNotFoundError,
    PersonaNotFoundError,
    ResponseStyleSnapshot,
    Scene,
    SceneDetails,
    StaleIdentityError,
    StalePersonaError,
    StaleStorylineError,
    StartingRelationship,
    StartStoryline,
    Storyline,
    StorylineGroup,
)
from chat_buddy.characters.infrastructure.db.models import (
    ContinuityModel,
    ConversationModel,
    IdentityModel,
    PersonaModel,
    SceneModel,
    StartingRelationshipModel,
    StorylineModel,
)


class DbStorylineRepository:
    """Persist Storyline ownership, metadata, and lifecycle atomically."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory:
                Factory used for short database transactions.
        """

        self._factory = session_factory

    def start(
        self, request: StartStoryline, relationship: StartingRelationship
    ) -> tuple[Storyline, Scene]:
        """Freeze reviewed profiles and create the Storyline's first scene.

        Args:
            request:
                Complete reviewed start confirmation.
            relationship:
                Resolved immutable starting relationship.

        Returns:
            The new result or the original result for an identical confirmation.
        """

        try:
            with self._factory() as session, session.begin():
                existing = self._confirmation(session, request)
                if existing is not None:
                    return self._start_snapshot(session, existing)

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

                existing = self._confirmation(session, request)
                if existing is not None:
                    return self._start_snapshot(session, existing)

                if identity.revision != request.identity_revision:
                    raise StaleIdentityError(
                        "Review the current identity before starting"
                    )
                if persona.revision != request.persona_revision:
                    raise StalePersonaError(
                        "Review the current persona before starting"
                    )
                if self._active(session, request.identity_id, request.persona_id):
                    raise ActiveStorylineError(
                        "Archive the active Storyline before starting a replacement"
                    )

                identity.is_frozen = True
                persona.is_frozen = True
                continuity = ContinuityModel(
                    identity_id=identity.id,
                    persona_id=persona.id,
                    mode="storyline",
                    lifecycle="active",
                    request_id=request.request_id,
                    confirmed_request=request.model_dump(mode="json"),
                )
                session.add(continuity)
                session.flush()

                storyline = StorylineModel(
                    continuity_id=continuity.id,
                    identity_id=identity.id,
                    persona_id=persona.id,
                    mode="storyline",
                    name=request.name,
                    revision=1,
                )
                conversation = ConversationModel(
                    continuity_id=continuity.id,
                    identity_id=identity.id,
                    persona_id=persona.id,
                    mode="storyline",
                )

                session.add_all(
                    [
                        storyline,
                        conversation,
                        StartingRelationshipModel(
                            continuity_id=continuity.id,
                            identity_id=identity.id,
                            persona_id=persona.id,
                            snapshot=relationship.model_dump(mode="json"),
                        ),
                    ]
                )
                session.flush()

                session.add(
                    SceneModel(
                        continuity_id=continuity.id,
                        identity_id=identity.id,
                        persona_id=persona.id,
                        conversation_id=conversation.id,
                        mode="storyline",
                        position=1,
                        title=request.initial_scene.title,
                        setup=request.initial_scene.setup,
                        response_style=request.initial_scene.response_style.model_dump(
                            mode="json"
                        ),
                        setup_locked=False,
                    )
                )
                session.flush()

                return self._start_snapshot(session, continuity)
        except IntegrityError:
            with self._factory() as session:
                existing = self._confirmation(session, request)
                if existing is not None:
                    return self._start_snapshot(session, existing)
                if self._active(session, request.identity_id, request.persona_id):
                    raise ActiveStorylineError(
                        "An active Storyline already exists"
                    ) from None
            raise

    def find_confirmation(
        self, request: StartStoryline
    ) -> tuple[Storyline, Scene] | None:
        """Find an identical prior confirmation.

        Args:
            request:
                Complete reviewed start confirmation.

        Returns:
            The original start result, or None.
        """

        with self._factory() as session:
            row = self._confirmation(session, request)
            return None if row is None else self._start_snapshot(session, row)

    def find_active(self, identity_id: UUID, persona_id: UUID) -> Storyline | None:
        """Find the pair's active Storyline.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.

        Returns:
            Active Storyline or None.
        """

        with self._factory() as session:
            row = self._active(session, identity_id, persona_id)
            return None if row is None else self._snapshot(session, row)

    def get(self, identity_id: UUID, persona_id: UUID, storyline_id: UUID) -> Storyline:
        """Read a Storyline under complete profile ownership.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            storyline_id:
                Requested Storyline continuity.

        Returns:
            Owned Storyline snapshot.
        """

        with self._factory() as session:
            row = self._owned(session, identity_id, persona_id, storyline_id)
            return self._snapshot(session, row)

    def list_for_pair(self, identity_id: UUID, persona_id: UUID) -> StorylineGroup:
        """List a pair's Storylines in stable identifier order.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.

        Returns:
            Validated deterministic Storyline group.
        """

        with self._factory() as session:
            rows = session.scalars(
                select(StorylineModel)
                .where(
                    StorylineModel.identity_id == identity_id,
                    StorylineModel.persona_id == persona_id,
                )
                .order_by(StorylineModel.continuity_id)
            )

            return StorylineGroup(
                identity_id=identity_id,
                persona_id=persona_id,
                storylines=tuple(self._snapshot(session, row) for row in rows),
            )

    def rename(
        self,
        identity_id: UUID,
        persona_id: UUID,
        storyline_id: UUID,
        name: str,
        expected_revision: int,
    ) -> Storyline:
        """Rename an active Storyline under its optimistic revision.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            storyline_id:
                Storyline continuity identifier.
            name:
                Replacement name.
            expected_revision:
                Last observed revision.

        Returns:
            Updated Storyline snapshot.
        """

        with self._factory() as session, session.begin():
            row = self._owned(session, identity_id, persona_id, storyline_id, lock=True)
            current = self._snapshot(session, row)
            replacement = current.model_copy(update={"name": name})
            replacement = Storyline.model_validate(replacement.model_dump())
            self._guard_write(session, row, expected_revision)

            row.name = replacement.name
            row.revision += 1
            session.flush()

            return self._snapshot(session, row)

    def archive(
        self,
        identity_id: UUID,
        persona_id: UUID,
        storyline_id: UUID,
        expected_revision: int,
    ) -> Storyline:
        """Permanently archive a Storyline and release the pair's active slot.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            storyline_id:
                Storyline continuity identifier.
            expected_revision:
                Last observed revision.

        Returns:
            Archived Storyline snapshot.
        """

        with self._factory() as session, session.begin():
            row = self._owned(session, identity_id, persona_id, storyline_id, lock=True)
            continuity = self._continuity(session, row, lock=True)

            if continuity.lifecycle == "archived":
                return self._snapshot(session, row)
            if row.revision != expected_revision:
                raise StaleStorylineError("Storyline changed before archival")

            continuity.lifecycle = "archived"
            row.revision += 1
            session.flush()

            return self._snapshot(session, row)

    @staticmethod
    def _confirmation(
        session: Session, request: StartStoryline
    ) -> ContinuityModel | None:
        """Resolve confirmation equality against all reviewed inputs.

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
    ) -> StorylineModel | None:
        """Find the active Storyline row for a pair.

        Args:
            session:
                Current session.
            identity_id:
                Identity owner.
            persona_id:
                Persona owner.

        Returns:
            Active Storyline row or None.
        """

        return session.scalar(
            select(StorylineModel)
            .join(
                ContinuityModel,
                ContinuityModel.id == StorylineModel.continuity_id,
            )
            .where(
                StorylineModel.identity_id == identity_id,
                StorylineModel.persona_id == persona_id,
                ContinuityModel.lifecycle == "active",
            )
        )

    @staticmethod
    def _owned(
        session: Session,
        identity_id: UUID,
        persona_id: UUID,
        storyline_id: UUID,
        lock: bool = False,
    ) -> StorylineModel:
        """Select one Storyline under complete ownership.

        Args:
            session:
                Current session.
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            storyline_id:
                Expected continuity identifier.
            lock:
                Whether to lock the Storyline row.

        Returns:
            Matching row.

        Raises:
            ContinuityNotFoundError:
                If ownership or mode does not match.
        """

        query = select(StorylineModel).where(
            StorylineModel.continuity_id == storyline_id,
            StorylineModel.identity_id == identity_id,
            StorylineModel.persona_id == persona_id,
            StorylineModel.mode == "storyline",
        )
        row = session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise ContinuityNotFoundError(str(storyline_id))
        return row

    @staticmethod
    def _continuity(
        session: Session, row: StorylineModel, lock: bool = False
    ) -> ContinuityModel:
        """Load the exact owning continuity.

        Args:
            session:
                Current session.
            row:
                Owned Storyline row.
            lock:
                Whether to lock lifecycle state.

        Returns:
            Exact Storyline continuity row.
        """

        query = select(ContinuityModel).where(
            ContinuityModel.id == row.continuity_id,
            ContinuityModel.identity_id == row.identity_id,
            ContinuityModel.persona_id == row.persona_id,
            ContinuityModel.mode == "storyline",
        )
        return session.scalars(query.with_for_update() if lock else query).one()

    @classmethod
    def _guard_write(
        cls, session: Session, row: StorylineModel, expected_revision: int
    ) -> None:
        """Require active lifecycle and current optimistic revision.

        Args:
            session:
                Current session.
            row:
                Locked Storyline row.
            expected_revision:
                Last observed revision.
        """

        continuity = cls._continuity(session, row, lock=True)
        if continuity.lifecycle != "active":
            raise ArchivedContinuityError("Archived Storylines are read-only")
        if row.revision != expected_revision:
            raise StaleStorylineError("Storyline changed; reload before writing")

    @classmethod
    def _snapshot(cls, session: Session, row: StorylineModel) -> Storyline:
        """Build a detached Storyline domain snapshot.

        Args:
            session:
                Current session.
            row:
                Storyline persistence row.

        Returns:
            Validated domain snapshot.
        """

        continuity = cls._continuity(session, row)
        relationship = session.scalars(
            select(StartingRelationshipModel).where(
                StartingRelationshipModel.continuity_id == row.continuity_id,
                StartingRelationshipModel.identity_id == row.identity_id,
                StartingRelationshipModel.persona_id == row.persona_id,
            )
        ).one()

        return Storyline(
            id=row.continuity_id,
            identity_id=row.identity_id,
            persona_id=row.persona_id,
            name=row.name,
            lifecycle=ContinuityLifecycle(continuity.lifecycle),
            relationship=StartingRelationship.model_validate(relationship.snapshot),
            revision=row.revision,
        )

    @staticmethod
    def _scene_snapshot(row: SceneModel) -> Scene:
        """Build a detached scene snapshot from one owned row.

        Args:
            row:
                Scene persistence row.

        Returns:
            Validated scene domain snapshot.
        """

        return Scene(
            id=row.id,
            scope=ConversationScope(
                identity_id=row.identity_id,
                persona_id=row.persona_id,
                continuity_id=row.continuity_id,
                conversation_id=row.conversation_id,
            ),
            position=row.position,
            details=SceneDetails(
                title=row.title,
                setup=row.setup,
                response_style=ResponseStyleSnapshot.model_validate(row.response_style),
            ),
            setup_locked=row.setup_locked,
        )

    @classmethod
    def _start_snapshot(
        cls, session: Session, continuity: ContinuityModel
    ) -> tuple[Storyline, Scene]:
        """Build the exact persisted initial start result.

        Args:
            session:
                Current session.
            continuity:
                Confirmed Storyline continuity.

        Returns:
            Storyline and its position-one scene.
        """

        storyline = session.scalars(
            select(StorylineModel).where(
                StorylineModel.continuity_id == continuity.id,
                StorylineModel.identity_id == continuity.identity_id,
                StorylineModel.persona_id == continuity.persona_id,
            )
        ).one()
        scene = session.scalars(
            select(SceneModel).where(
                SceneModel.continuity_id == continuity.id,
                SceneModel.position == 1,
            )
        ).one()

        return cls._snapshot(session, storyline), cls._scene_snapshot(scene)
