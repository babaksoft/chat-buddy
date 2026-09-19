from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from chat_buddy.chat.domain import (
    ChatRole,
    CompletedTurn,
    GenerationAttemptStatus,
    SummaryLifecycle,
    SummaryProvenance,
    SummaryRecord,
)
from chat_buddy.chat.infrastructure.db.models import (
    GenerationAttempt,
    Message,
    Summary,
)


class SummaryRepository:
    """Persists conversation-owned checkpointed summary versions."""

    def __init__(self, session: Session) -> None:
        """Initialize the repository.

        Args:
            session:
                SQLAlchemy session used for repository operations.
        """

        self._session = session

    def get_active_summary(self, conversation_id: UUID) -> SummaryRecord | None:
        """Return the active summary for a conversation.

        Args:
            conversation_id:
                Conversation whose active summary should be loaded.

        Returns:
            Active summary record, or ``None`` when absent.
        """

        statement = select(Summary).where(
            Summary.conversation_id == conversation_id,
            Summary.lifecycle == SummaryLifecycle.ACTIVE,
        )
        model = self._session.scalar(statement)
        return self._to_record(model) if model is not None else None

    def get_summary(self, summary_id: UUID) -> SummaryRecord | None:
        """Return one summary version.

        Args:
            summary_id:
                Identifier of the summary version.

        Returns:
            Matching summary record, or ``None`` when absent.
        """

        model = self._session.get(Summary, summary_id)
        return self._to_record(model) if model is not None else None

    def replace_active_summary(
        self,
        summary: SummaryRecord,
        *,
        expected_active_id: UUID | None,
    ) -> SummaryRecord:
        """Atomically replace the active summary using optimistic concurrency.

        Args:
            summary:
                Validated active summary version to persist.
            expected_active_id:
                Identifier expected to be active before replacement.

        Returns:
            Persisted active summary record.

        Raises:
            ValueError:
                If provenance or checkpoint ordering is invalid.
            RuntimeError:
                If the expected active version is stale.
            SQLAlchemyError:
                If persistence fails.
        """

        if summary.lifecycle is not SummaryLifecycle.ACTIVE:
            raise ValueError("A replacement summary must be active.")

        active = self._lock_active(summary.conversation_id)
        active_id = active.id if active is not None else None
        if active_id != expected_active_id:
            raise RuntimeError("The active summary changed before replacement.")
        if summary.predecessor_id != expected_active_id:
            raise ValueError(
                "Summary predecessor must match the expected active version."
            )

        checkpoint = self._completed_attempt_for_message(
            summary.checkpoint_message_id,
            summary.conversation_id,
        )
        if checkpoint is None:
            raise ValueError(
                "Summary checkpoint must be a completed assistant message in its conversation."
            )

        if active is not None:
            prior_checkpoint = self._completed_attempt_for_message(
                active.checkpoint_message_id,
                summary.conversation_id,
            )
            if prior_checkpoint is None:
                raise ValueError("The active summary has an invalid checkpoint.")
            if self._attempt_order(checkpoint) < self._attempt_order(prior_checkpoint):
                raise ValueError("A summary checkpoint cannot move backward.")
            active.lifecycle = SummaryLifecycle.SUPERSEDED

        model = Summary(
            id=summary.id,
            conversation_id=summary.conversation_id,
            content=summary.content,
            lifecycle=summary.lifecycle,
            predecessor_id=summary.predecessor_id,
            checkpoint_message_id=summary.checkpoint_message_id,
            created_at=summary.created_at,
        )
        try:
            self._session.add(model)
            self._session.commit()
            return summary
        except SQLAlchemyError:
            self._session.rollback()
            raise

    def get_uncovered_completed_turns(
        self, conversation_id: UUID
    ) -> tuple[CompletedTurn, ...]:
        """Return completed turns after the active summary checkpoint.

        Args:
            conversation_id:
                Conversation whose uncovered turns should be loaded.

        Returns:
            Completed turns in deterministic completion order.
        """

        user_message = aliased(Message)
        assistant_message = aliased(Message)
        statement = (
            select(GenerationAttempt, user_message, assistant_message)
            .join(
                user_message,
                user_message.id == GenerationAttempt.source_user_message_id,
            )
            .join(
                assistant_message,
                assistant_message.id == GenerationAttempt.assistant_message_id,
            )
            .where(
                GenerationAttempt.conversation_id == conversation_id,
                GenerationAttempt.status == GenerationAttemptStatus.COMPLETED,
                user_message.role == ChatRole.USER,
                assistant_message.role == ChatRole.ASSISTANT,
            )
            .order_by(GenerationAttempt.finished_at, GenerationAttempt.id)
        )
        rows = list(self._session.execute(statement))
        active = self.get_active_summary(conversation_id)
        if active is not None:
            positions = {
                attempt.assistant_message_id: index
                for index, (attempt, _, _) in enumerate(rows)
            }
            checkpoint_position = positions.get(active.checkpoint_message_id)
            if checkpoint_position is None:
                raise ValueError(
                    "The active summary checkpoint is not a completed turn."
                )
            rows = rows[checkpoint_position + 1 :]

        return tuple(
            CompletedTurn(
                conversation_id=attempt.conversation_id,
                attempt_id=attempt.id,
                user_message_id=user.id,
                assistant_message_id=assistant.id,
                user_content=attempt.submitted_user_content,
                assistant_content=assistant.content,
                completed_at=self._aware(attempt.finished_at),
            )
            for attempt, user, assistant in rows
        )

    def _lock_active(self, conversation_id: UUID) -> Summary | None:
        """Load the current active summary with a row lock.

        Args:
            conversation_id:
                Conversation whose summary should be locked.

        Returns:
            Locked active persistence entity, or ``None``.
        """

        statement = (
            select(Summary)
            .where(
                Summary.conversation_id == conversation_id,
                Summary.lifecycle == SummaryLifecycle.ACTIVE,
            )
            .with_for_update()
        )
        return self._session.scalar(statement)

    def _completed_attempt_for_message(
        self, message_id: UUID, conversation_id: UUID
    ) -> GenerationAttempt | None:
        """Load a completed attempt for one assistant checkpoint.

        Args:
            message_id:
                Assistant message identifier.
            conversation_id:
                Owning conversation identifier.

        Returns:
            Matching completed attempt, or ``None``.
        """

        statement = select(GenerationAttempt).where(
            GenerationAttempt.assistant_message_id == message_id,
            GenerationAttempt.conversation_id == conversation_id,
            GenerationAttempt.status == GenerationAttemptStatus.COMPLETED,
        )
        return self._session.scalar(statement)

    @staticmethod
    def _attempt_order(attempt: GenerationAttempt) -> tuple[datetime, UUID]:
        """Return a deterministic completion-order key.

        Args:
            attempt:
                Completed attempt to order.

        Returns:
            Completion timestamp and stable identifier.
        """

        return (SummaryRepository._aware(attempt.finished_at), attempt.id)

    @staticmethod
    def _to_record(model: Summary) -> SummaryRecord:
        """Translate a persistence entity into a domain record.

        Args:
            model:
                Persisted summary entity.

        Returns:
            Immutable summary record.
        """

        return SummaryRecord(
            id=model.id,
            conversation_id=model.conversation_id,
            content=model.content,
            created_at=SummaryRepository._aware(model.created_at),
            lifecycle=model.lifecycle,
            provenance=SummaryProvenance(
                conversation_id=model.conversation_id,
                checkpoint_message_id=model.checkpoint_message_id,
                predecessor_id=model.predecessor_id,
            ),
        )

    @staticmethod
    def _aware(value: datetime | None) -> datetime:
        """Normalize a required SQLite timestamp to UTC.

        Args:
            value:
                Persisted timestamp.

        Returns:
            Timezone-aware timestamp.

        Raises:
            ValueError:
                If the required timestamp is absent.
        """

        if value is None:
            raise ValueError("Required persisted timestamp is absent.")
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
