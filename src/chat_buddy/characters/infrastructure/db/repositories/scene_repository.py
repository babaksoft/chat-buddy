"""Ordered Storyline scene persistence with complete ownership guards."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    ConversationScope,
    IncompleteLatestSceneError,
    InvalidSceneOwnershipError,
    LockedSceneSetupError,
    ResponseStyleSnapshot,
    Scene,
    SceneAppendEligibility,
    SceneDetails,
    SceneSequence,
    StaleSelectionError,
    Storyline,
)
from chat_buddy.characters.infrastructure.db.models import (
    ContinuityModel,
    ConversationModel,
    GenerationAttemptModel,
    MessageModel,
    SceneModel,
    StorylineModel,
)
from chat_buddy.characters.infrastructure.db.repositories.storyline_repository import (
    DbStorylineRepository,
)


class DbSceneRepository:
    """Persist append-only scenes and guarded authored metadata."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory:
                Factory used for short database transactions.
        """

        self._factory = session_factory

    def get(self, scope: ConversationScope, scene_id: UUID) -> Scene:
        """Read a scene under complete conversation ownership.

        Args:
            scope:
                Expected complete ownership.
            scene_id:
                Requested scene identifier.

        Returns:
            Owned scene snapshot.
        """

        with self._factory() as session:
            return self._snapshot(self._owned(session, scope, scene_id))

    def list(self, storyline: Storyline) -> SceneSequence:
        """List a Storyline's scenes in immutable chronological order.

        Args:
            storyline:
                Expected owning Storyline snapshot.

        Returns:
            Validated scene sequence.
        """

        with self._factory() as session:
            row = DbStorylineRepository._owned(
                session,
                storyline.identity_id,
                storyline.persona_id,
                storyline.id,
            )

            return self._sequence(session, row)

    def append_next(
        self, details: SceneDetails, eligibility: SceneAppendEligibility
    ) -> SceneSequence:
        """Append one next scene if submitted and persisted facts are eligible.

        Args:
            details:
                Authored metadata and fixed response style.
            eligibility:
                Last observed append facts and optimistic guards.

        Returns:
            Complete updated scene sequence.
        """

        if not eligibility.can_append:
            raise IncompleteLatestSceneError(str(eligibility.block_reason))

        with self._factory() as session, session.begin():
            # Ensure parent storyline exists
            storyline = session.scalar(
                select(StorylineModel)
                .where(StorylineModel.continuity_id == eligibility.storyline_id)
                .with_for_update()
            )
            if storyline is None:
                raise InvalidSceneOwnershipError(str(eligibility.storyline_id))

            # Ensure storyline is writable and latest scene hasn't changed
            DbStorylineRepository._guard_write(
                session, storyline, eligibility.expected_storyline_revision
            )
            latest = session.scalars(
                select(SceneModel)
                .where(SceneModel.continuity_id == storyline.continuity_id)
                .order_by(SceneModel.position.desc())
                .with_for_update()
            ).first()
            if latest is None or (
                latest.id != eligibility.scene_id
                or latest.position != eligibility.scene_position
            ):
                raise IncompleteLatestSceneError(
                    "The observed scene is no longer the latest"
                )

            # Ensure selected conversation path hasn't changed
            conversation = session.scalars(
                select(ConversationModel)
                .where(
                    ConversationModel.id == latest.conversation_id,
                    ConversationModel.continuity_id == latest.continuity_id,
                    ConversationModel.mode == "storyline",
                )
                .with_for_update()
            ).one()
            if conversation.selected_leaf_id != eligibility.expected_selected_leaf_id:
                raise StaleSelectionError("Scene selection changed before append")

            # Ensure latest scene has no open generation attempt
            leaf = (
                None
                if conversation.selected_leaf_id is None
                else session.get(MessageModel, conversation.selected_leaf_id)
            )
            open_attempt = session.scalar(
                select(GenerationAttemptModel.id).where(
                    GenerationAttemptModel.conversation_id == conversation.id,
                    GenerationAttemptModel.status.in_(("pending", "streaming")),
                )
            )
            if leaf is None or leaf.role != "persona" or open_attempt is not None:
                raise IncompleteLatestSceneError(
                    "The persisted latest scene has no complete idle exchange"
                )

            # Atomically create new conversation, new scene and update storyline revision
            new_conversation = ConversationModel(
                continuity_id=storyline.continuity_id,
                identity_id=storyline.identity_id,
                persona_id=storyline.persona_id,
                mode="storyline",
            )
            session.add(new_conversation)
            session.flush()

            session.add(
                SceneModel(
                    continuity_id=storyline.continuity_id,
                    identity_id=storyline.identity_id,
                    persona_id=storyline.persona_id,
                    conversation_id=new_conversation.id,
                    mode="storyline",
                    position=latest.position + 1,
                    title=details.title,
                    setup=details.setup,
                    response_style=details.response_style.model_dump(mode="json"),
                    setup_locked=False,
                )
            )
            storyline.revision += 1
            session.flush()

            return self._sequence(session, storyline)

    def rename(
        self,
        scope: ConversationScope,
        scene_id: UUID,
        title: str,
        expected_storyline_revision: int,
    ) -> Scene:
        """Rename a scene under Storyline ownership and revision guards.

        Args:
            scope:
                Complete expected ownership.
            scene_id:
                Scene identifier.
            title:
                Replacement presentation title.
            expected_storyline_revision:
                Last observed Storyline revision.

        Returns:
            Updated scene snapshot.
        """

        with self._factory() as session, session.begin():
            scene, storyline = self._writable(
                session, scope, scene_id, expected_storyline_revision
            )
            validated = SceneDetails(
                title=title,
                setup=scene.setup,
                response_style=ResponseStyleSnapshot.model_validate(
                    scene.response_style
                ),
            )

            scene.title = validated.title
            storyline.revision += 1
            session.flush()

            return self._snapshot(scene)

    def replace_setup(
        self,
        scope: ConversationScope,
        scene_id: UUID,
        setup: str,
        expected_storyline_revision: int,
    ) -> Scene:
        """Replace an unlocked latest scene setup under revision guards.

        Args:
            scope:
                Complete expected ownership.
            scene_id:
                Scene identifier.
            setup:
                Replacement setup.
            expected_storyline_revision:
                Last observed Storyline revision.

        Returns:
            Updated scene snapshot.
        """

        with self._factory() as session, session.begin():
            scene, storyline = self._writable(
                session, scope, scene_id, expected_storyline_revision
            )
            if scene.setup_locked:
                raise LockedSceneSetupError("Scene setup is already locked")

            latest_position = session.scalar(
                select(SceneModel.position)
                .where(SceneModel.continuity_id == scope.continuity_id)
                .order_by(SceneModel.position.desc())
                .limit(1)
            )
            if scene.position != latest_position:
                raise LockedSceneSetupError("Only the latest scene setup is writable")

            validated = SceneDetails(
                title=scene.title,
                setup=setup,
                response_style=ResponseStyleSnapshot.model_validate(
                    scene.response_style
                ),
            )

            scene.setup = validated.setup
            storyline.revision += 1
            session.flush()

            return self._snapshot(scene)

    def lock_setup(
        self,
        scope: ConversationScope,
        scene_id: UUID,
        expected_selected_leaf_id: UUID | None,
    ) -> Scene:
        """Serialize setup freezing against the observed conversation leaf.

        Args:
            scope:
                Complete expected ownership.
            scene_id:
                Scene identifier.
            expected_selected_leaf_id:
                Last observed selected leaf.

        Returns:
            Setup-locked scene snapshot.
        """

        with self._factory() as session, session.begin():
            scene = self._owned(session, scope, scene_id, lock=True)
            continuity = session.scalars(
                select(ContinuityModel)
                .where(
                    ContinuityModel.id == scope.continuity_id,
                    ContinuityModel.mode == "storyline",
                )
                .with_for_update()
            ).one()
            if continuity.lifecycle != "active":
                raise ArchivedContinuityError("Archived Storylines are read-only")

            conversation = session.scalars(
                select(ConversationModel)
                .where(
                    ConversationModel.id == scope.conversation_id,
                    ConversationModel.continuity_id == scope.continuity_id,
                    ConversationModel.mode == "storyline",
                )
                .with_for_update()
            ).one()
            if conversation.selected_leaf_id != expected_selected_leaf_id:
                raise StaleSelectionError("Scene selection changed before setup lock")

            scene.setup_locked = True
            session.flush()

            return self._snapshot(scene)

    @staticmethod
    def _owned(
        session: Session,
        scope: ConversationScope,
        scene_id: UUID,
        lock: bool = False,
    ) -> SceneModel:
        """Select a scene using every ownership component.

        Args:
            session:
                Current session.
            scope:
                Expected complete ownership.
            scene_id:
                Scene identifier.
            lock:
                Whether to lock the scene row.

        Returns:
            Matching scene row.

        Raises:
            InvalidSceneOwnershipError:
                If any ownership component differs.
        """

        query = select(SceneModel).where(
            SceneModel.id == scene_id,
            SceneModel.identity_id == scope.identity_id,
            SceneModel.persona_id == scope.persona_id,
            SceneModel.continuity_id == scope.continuity_id,
            SceneModel.conversation_id == scope.conversation_id,
            SceneModel.mode == "storyline",
        )
        row = session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise InvalidSceneOwnershipError(str(scene_id))
        return row

    @classmethod
    def _writable(
        cls,
        session: Session,
        scope: ConversationScope,
        scene_id: UUID,
        expected_revision: int,
    ) -> tuple[SceneModel, StorylineModel]:
        """Lock a scene and require writable current Storyline state.

        Args:
            session:
                Current session.
            scope:
                Complete ownership.
            scene_id:
                Scene identifier.
            expected_revision:
                Last observed Storyline revision.

        Returns:
            Locked scene and Storyline rows.
        """

        scene = cls._owned(session, scope, scene_id, lock=True)
        storyline = session.scalars(
            select(StorylineModel)
            .where(StorylineModel.continuity_id == scope.continuity_id)
            .with_for_update()
        ).one()
        DbStorylineRepository._guard_write(session, storyline, expected_revision)

        return scene, storyline

    @classmethod
    def _sequence(cls, session: Session, storyline: StorylineModel) -> SceneSequence:
        """Build a complete ordered sequence in the current transaction.

        Args:
            session:
                Current session.
            storyline:
                Owned Storyline row.

        Returns:
            Validated sequence snapshot.
        """

        rows = session.scalars(
            select(SceneModel)
            .where(SceneModel.continuity_id == storyline.continuity_id)
            .order_by(SceneModel.position)
        )

        return SceneSequence(
            storyline=DbStorylineRepository._snapshot(session, storyline),
            scenes=tuple(cls._snapshot(row) for row in rows),
        )

    @staticmethod
    def _snapshot(row: SceneModel) -> Scene:
        """Build a detached scene domain snapshot.

        Args:
            row:
                Scene persistence row.

        Returns:
            Validated scene snapshot.
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
