"""Atomic persistence for owned immutable summary revisions."""

from datetime import UTC
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    ConversationNotFoundError,
    ConversationScope,
    EffectiveGeneration,
    SummaryConflictError,
    SummaryRevision,
)
from chat_buddy.characters.infrastructure.db.models import (
    ContinuityModel,
    ConversationModel,
    MessageModel,
    SummaryRevisionModel,
)


class DbSummaryRepository:
    """Persist one active summary under continuity and lineage locks."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Initialize the summary repository.

        Args:
            session_factory:
                Factory used for creating database sessions.
        """

        self._factory = session_factory

    def get_active(self, scope: ConversationScope) -> SummaryRevision | None:
        """Load the active revision only after verifying complete ownership.

        Args:
            scope:
                Complete required ownership.

        Returns:
            Active detached revision when present.
        """

        with self._factory() as session, session.begin():
            self._owned(session, scope)
            row = session.scalar(
                select(SummaryRevisionModel).where(
                    SummaryRevisionModel.conversation_id == scope.conversation_id,
                    SummaryRevisionModel.continuity_id == scope.continuity_id,
                    SummaryRevisionModel.is_active.is_(True),
                )
            )

            return self._summary(scope, row) if row is not None else None

    def replace(
        self,
        replacement: SummaryRevision,
        expected_revision: int | None,
        expected_checkpoint_id: UUID | None,
    ) -> SummaryRevision:
        """Atomically validate ownership, checkpoint, and expected lineage.

        Args:
            replacement:
                Proposed active successor.
            expected_revision:
                Previously observed active revision.
            expected_checkpoint_id:
                Previously observed checkpoint.

        Returns:
            Persisted active revision.

        Raises:
            SummaryConflictError:
                If the lineage is stale or the checkpoint is invalid.
        """

        if not replacement.is_active:
            raise SummaryConflictError("A replacement must become active.")

        scope = replacement.scope
        try:
            with self._factory() as session, session.begin():
                self._owned(session, scope, lock=True, writable=True)
                active = session.scalar(
                    select(SummaryRevisionModel)
                    .where(
                        SummaryRevisionModel.conversation_id == scope.conversation_id,
                        SummaryRevisionModel.continuity_id == scope.continuity_id,
                        SummaryRevisionModel.is_active.is_(True),
                    )
                    .with_for_update()
                )

                self._validate_lineage(
                    active, replacement, expected_revision, expected_checkpoint_id
                )

                checkpoint = session.scalar(
                    select(MessageModel).where(
                        MessageModel.id == replacement.checkpoint_message_id,
                        MessageModel.conversation_id == scope.conversation_id,
                        MessageModel.continuity_id == scope.continuity_id,
                        MessageModel.role == "persona",
                        MessageModel.sequence == replacement.checkpoint_sequence,
                    )
                )
                if checkpoint is None:
                    raise SummaryConflictError(
                        "Summary checkpoint is not an owned turn."
                    )

                if active is not None:
                    active.is_active = False
                row = SummaryRevisionModel(
                    id=replacement.id,
                    conversation_id=scope.conversation_id,
                    continuity_id=scope.continuity_id,
                    revision=replacement.revision,
                    predecessor_id=replacement.predecessor_id,
                    checkpoint_message_id=replacement.checkpoint_message_id,
                    checkpoint_sequence=replacement.checkpoint_sequence,
                    content=replacement.content,
                    generation=replacement.generation.model_dump(mode="json"),
                    is_active=True,
                    created_at=replacement.created_at,
                )
                session.add(row)
                session.flush()

                return self._summary(scope, row)
        except IntegrityError:
            raise SummaryConflictError(
                "Summary lineage changed concurrently."
            ) from None

    @staticmethod
    def _owned(
        session: Session,
        scope: ConversationScope,
        lock: bool = False,
        writable: bool = False,
    ) -> None:
        """Verify all ownership components and optionally lock the continuity.

        Args:
            session:
                Current transaction.
            scope:
                Complete required ownership.
            lock:
                Whether to lock the underlying continuity.
            writable:
                Whether archived continuity must be rejected.

        Raises:
            ConversationNotFoundError:
                If any ownership identifier is foreign.
            ArchivedContinuityError:
                If a write targets an archived continuity.
        """

        statement = select(ContinuityModel).where(
            ContinuityModel.id == scope.continuity_id,
            ContinuityModel.identity_id == scope.identity_id,
            ContinuityModel.persona_id == scope.persona_id,
        )
        if lock:
            statement = statement.with_for_update()
        continuity = session.scalar(statement)
        conversation_id = session.scalar(
            select(ConversationModel.id).where(
                ConversationModel.id == scope.conversation_id,
                ConversationModel.continuity_id == scope.continuity_id,
                ConversationModel.identity_id == scope.identity_id,
                ConversationModel.persona_id == scope.persona_id,
            )
        )

        if continuity is None or conversation_id is None:
            raise ConversationNotFoundError("Summary ownership does not match.")
        if writable and continuity.lifecycle != "active":
            raise ArchivedContinuityError("Archived continuity is read-only.")

    @staticmethod
    def _validate_lineage(
        active: SummaryRevisionModel | None,
        replacement: SummaryRevision,
        expected_revision: int | None,
        expected_checkpoint_id: UUID | None,
    ) -> None:
        """Reject stale replacement or nonadvancing checkpoints.

        Args:
            active:
                Locked current active row.
            replacement:
                Proposed successor.
            expected_revision:
                Caller's observed revision.
            expected_checkpoint_id:
                Caller's observed checkpoint.

        Raises:
            SummaryConflictError:
                If any lineage invariant fails.
        """

        if active is None:
            if (
                expected_revision is not None
                or expected_checkpoint_id is not None
                or replacement.revision != 1
                or replacement.predecessor_id is not None
            ):
                raise SummaryConflictError("Expected summary lineage is stale.")
            return

        if (
            active.revision != expected_revision
            or active.checkpoint_message_id != expected_checkpoint_id
            or replacement.revision != active.revision + 1
            or replacement.predecessor_id != active.id
            or replacement.checkpoint_sequence <= active.checkpoint_sequence
        ):
            raise SummaryConflictError("Expected summary lineage is stale.")

    @staticmethod
    def _summary(
        scope: ConversationScope, row: SummaryRevisionModel
    ) -> SummaryRevision:
        """Detach one validated domain revision.

        Args:
            scope:
                Verified complete ownership.
            row:
                Persisted revision row.

        Returns:
            Immutable domain snapshot.
        """

        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        else:
            created_at = created_at.astimezone(UTC)

        return SummaryRevision(
            id=row.id,
            scope=scope,
            revision=row.revision,
            predecessor_id=row.predecessor_id,
            checkpoint_message_id=row.checkpoint_message_id,
            checkpoint_sequence=row.checkpoint_sequence,
            content=row.content,
            generation=EffectiveGeneration.model_validate(row.generation),
            is_active=row.is_active,
            created_at=created_at,
        )
