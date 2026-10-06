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
    """Persist branch-addressable summaries under continuity and lineage locks."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Initialize the summary repository.

        Args:
            session_factory:
                Factory used for creating database sessions.
        """

        self._factory = session_factory

    def get_current(
        self, scope: ConversationScope, path_leaf_id: UUID | None = None
    ) -> SummaryRevision | None:
        """Load the deepest selected-ancestry-compatible revision.

        Args:
            scope:
                Complete required ownership.
            path_leaf_id:
                Exact ancestry leaf, or the selected leaf when absent.

        Returns:
            Current compatible detached revision when present.
        """

        with self._factory() as session, session.begin():
            self._owned(session, scope)
            positions = self._path_positions(session, scope, path_leaf_id)
            rows = tuple(
                session.scalars(
                    select(SummaryRevisionModel).where(
                        SummaryRevisionModel.conversation_id == scope.conversation_id,
                        SummaryRevisionModel.continuity_id == scope.continuity_id,
                        SummaryRevisionModel.checkpoint_message_id.in_(positions),
                    )
                )
            )
            row = max(
                rows,
                key=lambda candidate: (
                    positions[candidate.checkpoint_message_id],
                    candidate.revision,
                    candidate.created_at,
                    str(candidate.id),
                ),
                default=None,
            )
            return (
                self._summary(scope, row, positions[row.checkpoint_message_id])
                if row is not None
                else None
            )

    def append(
        self,
        replacement: SummaryRevision,
        expected_revision: int | None,
        expected_checkpoint_id: UUID | None,
    ) -> SummaryRevision:
        """Atomically validate and append one immutable lineage successor.

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

        scope = replacement.scope
        try:
            with self._factory() as session, session.begin():
                self._owned(session, scope, lock=True, writable=True)
                positions = self._path_positions(session, scope)
                candidates = tuple(
                    session.scalars(
                        select(SummaryRevisionModel)
                        .where(
                            SummaryRevisionModel.conversation_id
                            == scope.conversation_id,
                            SummaryRevisionModel.continuity_id == scope.continuity_id,
                            SummaryRevisionModel.checkpoint_message_id.in_(positions),
                        )
                        .with_for_update()
                    )
                )
                active_row = max(
                    candidates,
                    key=lambda candidate: (
                        positions[candidate.checkpoint_message_id],
                        candidate.revision,
                        candidate.created_at,
                        str(candidate.id),
                    ),
                    default=None,
                )
                active = (
                    self._summary(
                        scope,
                        active_row,
                        positions[active_row.checkpoint_message_id],
                    )
                    if active_row is not None
                    else None
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
                    )
                )
                if (
                    checkpoint is None
                    or positions.get(checkpoint.id) != replacement.checkpoint_sequence
                ):
                    raise SummaryConflictError(
                        "Summary checkpoint is not an owned turn."
                    )

                row = SummaryRevisionModel(
                    id=replacement.id,
                    conversation_id=scope.conversation_id,
                    continuity_id=scope.continuity_id,
                    revision=replacement.revision,
                    predecessor_id=replacement.predecessor_id,
                    checkpoint_message_id=replacement.checkpoint_message_id,
                    content=replacement.content,
                    generation=replacement.generation.model_dump(mode="json"),
                    created_at=replacement.created_at,
                )
                session.add(row)
                session.flush()

                return self._summary(scope, row, replacement.checkpoint_sequence)
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
        active: SummaryRevision | None,
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
        scope: ConversationScope, row: SummaryRevisionModel, checkpoint_sequence: int
    ) -> SummaryRevision:
        """Detach one validated domain revision.

        Args:
            scope:
                Verified complete ownership.
            row:
                Persisted revision row.
            checkpoint_sequence:
                Selected-path position derived from parent traversal.

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
            checkpoint_sequence=checkpoint_sequence,
            content=row.content,
            generation=EffectiveGeneration.model_validate(row.generation),
            created_at=created_at,
        )

    @staticmethod
    def _path_positions(
        session: Session,
        scope: ConversationScope,
        path_leaf_id: UUID | None = None,
    ) -> dict[UUID, int]:
        """Return selected ancestry positions derived only from parent links.

        Args:
            session:
                Current transaction.
            scope:
                Verified complete ownership.
            path_leaf_id:
                Exact ancestry leaf, or the selected leaf when absent.

        Returns:
            Message identifiers mapped to one-based path positions.
        """

        selected_leaf_id = path_leaf_id
        if selected_leaf_id is None:
            selected_leaf_id = session.scalar(
                select(ConversationModel.selected_leaf_id).where(
                    ConversationModel.id == scope.conversation_id,
                    ConversationModel.continuity_id == scope.continuity_id,
                )
            )
        if selected_leaf_id is None:
            return {}
        messages = tuple(
            session.scalars(
                select(MessageModel).where(
                    MessageModel.conversation_id == scope.conversation_id,
                    MessageModel.continuity_id == scope.continuity_id,
                )
            )
        )
        by_id = {message.id: message for message in messages}
        current = by_id.get(selected_leaf_id)
        reversed_ids: list[UUID] = []
        while current is not None:
            reversed_ids.append(current.id)
            current = by_id.get(current.parent_id) if current.parent_id else None
        return {
            message_id: position
            for position, message_id in enumerate(reversed(reversed_ids), start=1)
        }
