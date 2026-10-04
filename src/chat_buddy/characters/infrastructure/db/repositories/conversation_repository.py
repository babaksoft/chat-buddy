"""Short transactions with continuity locks and immutable provenance."""

from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    AttemptConflictError,
    AttemptStatus,
    ConversationHistory,
    ConversationNotFoundError,
    ConversationScope,
    ConversationSettings,
    EffectiveGeneration,
    GenerationAttempt,
    IncompleteTurnError,
    InvalidProviderResponseError,
    Message,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.models import (
    ContinuityModel,
    ConversationModel,
    GenerationAttemptModel,
    MessageModel,
)


class DbConversationRepository:
    """Persist sole-path turns under the same row lock used by archive."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Initialize the conversation repository.

        Args:
            session_factory:
                Factory used for creating database sessions.
        """

        self._factory = session_factory

    def history(self, scope: ConversationScope) -> ConversationHistory:
        """Read committed history and attempt provenance.

        Args:
            scope:
                Complete required ownership.

        Returns:
            Detached domain snapshot.
        """

        with self._factory() as session, session.begin():
            row = self._owned(session, scope)
            return self._history(session, scope, row)

    def configure(
        self, scope: ConversationScope, settings: ConversationSettings
    ) -> None:
        """Save next-attempt defaults on a writable conversation.

        Args:
            scope:
                Complete required ownership.
            settings:
                Validated requested selection.
        """

        with self._factory() as session, session.begin():
            row = self._owned(session, scope, writable=True)
            row.generation_settings = settings.model_dump(mode="json")

    def begin(
        self,
        scope: ConversationScope,
        generation: EffectiveGeneration,
        settings: ConversationSettings,
        expected_sequence: int,
        submitted: SubmittedInput | None,
    ) -> GenerationAttempt:
        """Atomically reserve an attempt and optionally append its user message.

        Args:
            scope:
                Complete required ownership.
            generation:
                Immutable effective response configuration.
            settings:
                Current requested selection to persist.
            expected_sequence:
                Last message position observed during prompt preflight.
            submitted:
                New input, or None to continue the existing unmatched tail.

        Returns:
            Detached domain snapshot.
        """

        if generation.capability != "response":
            raise ValueError("A response generation is required")

        with self._factory() as session, session.begin():
            row = self._owned(session, scope, writable=True)
            if (
                row.generation_settings is not None
                and row.generation_settings != settings.model_dump(mode="json")
            ):
                raise AttemptConflictError("Generation defaults changed; prepare again")
            history = self._history(session, scope, row)
            if any(a.status in {"pending", "streaming"} for a in history.attempts):
                raise AttemptConflictError("An attempt is already active")
            tail = history.messages[-1] if history.messages else None
            if (tail.sequence if tail else 0) != expected_sequence:
                raise AttemptConflictError("History changed; prepare the prompt again")
            now = datetime.now(UTC)
            if submitted is not None:
                if tail is not None and tail.role == "user":
                    raise IncompleteTurnError("Continue the unmatched user message")
                message = MessageModel(
                    conversation_id=scope.conversation_id,
                    continuity_id=scope.continuity_id,
                    sequence=expected_sequence + 1,
                    role="user",
                    content=submitted.content,
                    created_at=now,
                )
                session.add(message)
                session.flush()
                user_id, content = message.id, message.content
            else:
                if tail is None or tail.role != "user":
                    raise IncompleteTurnError("There is no incomplete turn to continue")
                user_id, content = tail.id, tail.content
            row.generation_settings = settings.model_dump(mode="json")
            attempt = GenerationAttemptModel(
                conversation_id=scope.conversation_id,
                continuity_id=scope.continuity_id,
                user_message_id=user_id,
                submitted_input=content,
                generation=generation.model_dump(mode="json"),
                status="pending",
                incomplete_output="",
                created_at=now,
                updated_at=now,
            )
            session.add(attempt)
            session.flush()
            return self._attempt(scope, attempt)

    def claim(self, scope: ConversationScope, attempt_id: UUID) -> GenerationAttempt:
        """Atomically transition a pending attempt to streaming.

        Args:
            scope:
                Complete required ownership.
            attempt_id:
                Pending attempt identifier.

        Returns:
            Detached domain snapshot.
        """

        with self._factory() as session, session.begin():
            self._owned(session, scope, writable=True)
            attempt = self._find_attempt(session, scope, attempt_id)
            self._require_status(attempt, "pending")
            attempt.status = "streaming"
            attempt.updated_at = datetime.now(UTC)
            session.flush()
            return self._attempt(scope, attempt)

    def append(self, scope: ConversationScope, attempt_id: UUID, chunk: str) -> None:
        """Persist progress and refresh its heartbeat.

        Args:
            scope:
                Complete required ownership.
            attempt_id:
                Streaming attempt identifier.
            chunk:
                New output text.
        """

        with self._factory() as session, session.begin():
            self._owned(session, scope, writable=True)
            attempt = self._find_attempt(session, scope, attempt_id)
            self._require_status(attempt, "streaming")
            attempt.incomplete_output += chunk
            attempt.updated_at = datetime.now(UTC)

    def complete(self, scope: ConversationScope, attempt_id: UUID) -> Message:
        """Atomically append a persona message and complete its attempt.

        Args:
            scope:
                Complete required ownership.
            attempt_id:
                Streaming attempt identifier.

        Returns:
            Detached domain snapshot.
        """

        with self._factory() as session, session.begin():
            row = self._owned(session, scope, writable=True)
            attempt = self._find_attempt(session, scope, attempt_id)
            self._require_status(attempt, "streaming")
            history = self._history(session, scope, row)
            tail = history.messages[-1]
            if tail.id != attempt.user_message_id or tail.role != "user":
                raise AttemptConflictError("Attempt no longer owns the unmatched tail")
            if not attempt.incomplete_output.strip():
                raise InvalidProviderResponseError(
                    "Provider returned an empty response"
                )
            now = datetime.now(UTC)
            message = MessageModel(
                conversation_id=scope.conversation_id,
                continuity_id=scope.continuity_id,
                sequence=tail.sequence + 1,
                role="persona",
                content=attempt.incomplete_output,
                reply_to=tail.id,
                created_at=now,
            )
            session.add(message)
            session.flush()
            attempt.persona_message_id = message.id
            attempt.status = "completed"
            attempt.updated_at = attempt.finished_at = now
            session.flush()
            return self._message(scope, message)

    def stop(
        self,
        scope: ConversationScope,
        attempt_id: UUID,
        status: Literal["failed", "interrupted"],
    ) -> None:
        """Terminate an open attempt without modifying committed history.

        Args:
            scope:
                Complete required ownership.
            attempt_id:
                Attempt to terminate.
            status:
                Terminal failure or interruption status.
        """

        with self._factory() as session, session.begin():
            self._owned(session, scope)
            attempt = self._find_attempt(session, scope, attempt_id)
            if attempt.status in {"pending", "streaming"}:
                attempt.status = status
                attempt.updated_at = attempt.finished_at = datetime.now(UTC)

    def reconcile(
        self, scope: ConversationScope, inactive_before: datetime
    ) -> ConversationHistory:
        """Interrupt expired attempts while fencing their late output.

        Args:
            scope:
                Complete required ownership.
            inactive_before:
                Only heartbeats at or before this UTC cutoff are abandoned.

        Returns:
            Detached domain snapshot.
        """

        with self._factory() as session, session.begin():
            row = self._owned(session, scope)
            attempts = session.scalars(
                select(GenerationAttemptModel).where(
                    GenerationAttemptModel.conversation_id == scope.conversation_id,
                    GenerationAttemptModel.continuity_id == scope.continuity_id,
                    GenerationAttemptModel.status.in_(["pending", "streaming"]),
                    GenerationAttemptModel.updated_at <= inactive_before,
                )
            )
            for attempt in attempts:
                attempt.status = "interrupted"
                attempt.updated_at = attempt.finished_at = datetime.now(UTC)
            session.flush()
            return self._history(session, scope, row)

    @staticmethod
    def _owned(
        session: Session, scope: ConversationScope, writable: bool = False
    ) -> ConversationModel:
        """Lock continuity first so all writers serialize with archival.

        Args:
            session:
                Current transaction.
            scope:
                Required ownership.
            writable:
                Whether archived lifecycle must be rejected.

        Returns:
            Owned conversation row.

        Raises:
            ConversationNotFoundError:
                If any ownership identifier is foreign.
            ArchivedContinuityError:
                If a write targets an archive.
        """

        continuity = session.scalar(
            select(ContinuityModel)
            .where(
                ContinuityModel.id == scope.continuity_id,
                ContinuityModel.identity_id == scope.identity_id,
                ContinuityModel.persona_id == scope.persona_id,
            )
            .with_for_update()
        )
        if continuity is None:
            raise ConversationNotFoundError("Conversation ownership does not match")
        row = session.scalar(
            select(ConversationModel).where(
                ConversationModel.id == scope.conversation_id,
                ConversationModel.continuity_id == scope.continuity_id,
                ConversationModel.identity_id == scope.identity_id,
                ConversationModel.persona_id == scope.persona_id,
            )
        )
        if row is None:
            raise ConversationNotFoundError("Conversation ownership does not match")
        if writable and continuity.lifecycle != "active":
            raise ArchivedContinuityError("Archived continuity is read-only")
        return row

    @staticmethod
    def _find_attempt(
        session: Session, scope: ConversationScope, attempt_id: UUID
    ) -> GenerationAttemptModel:
        """Read an attempt only within its conversation ownership.

        Args:
            session:
                Current transaction.
            scope:
                Required ownership.
            attempt_id:
                Requested attempt.

        Returns:
            Owned attempt row.

        Raises:
            ConversationNotFoundError:
                If the attempt belongs elsewhere.
        """

        row = session.scalar(
            select(GenerationAttemptModel).where(
                GenerationAttemptModel.id == attempt_id,
                GenerationAttemptModel.conversation_id == scope.conversation_id,
                GenerationAttemptModel.continuity_id == scope.continuity_id,
            )
        )
        if row is None:
            raise ConversationNotFoundError("Attempt ownership does not match")
        return row

    @staticmethod
    def _require_status(attempt: GenerationAttemptModel, status: str) -> None:
        """Fence stale or duplicate attempt mutations.

        Args:
            attempt:
                Owned attempt row.
            status:
                Required source state.

        Raises:
            AttemptConflictError:
                If the attempt has already moved on.
        """

        if attempt.status != status:
            raise AttemptConflictError("Attempt is no longer in the required state")

    @classmethod
    def _history(
        cls, session: Session, scope: ConversationScope, row: ConversationModel
    ) -> ConversationHistory:
        """Read only the owned messages and attempts in deterministic order.

        Args:
            session:
                Current transaction.
            scope:
                Required ownership.
            row:
                Owned conversation.

        Returns:
            Detached immutable history.
        """

        messages = session.scalars(
            select(MessageModel)
            .where(
                MessageModel.conversation_id == scope.conversation_id,
                MessageModel.continuity_id == scope.continuity_id,
            )
            .order_by(MessageModel.sequence)
        )
        attempts = session.scalars(
            select(GenerationAttemptModel)
            .where(
                GenerationAttemptModel.conversation_id == scope.conversation_id,
                GenerationAttemptModel.continuity_id == scope.continuity_id,
            )
            .order_by(GenerationAttemptModel.created_at, GenerationAttemptModel.id)
        )
        return ConversationHistory(
            scope=scope,
            settings=(
                ConversationSettings.model_validate(row.generation_settings)
                if row.generation_settings
                else None
            ),
            messages=tuple(cls._message(scope, message) for message in messages),
            attempts=tuple(cls._attempt(scope, attempt) for attempt in attempts),
        )

    @staticmethod
    def _message(scope: ConversationScope, row: MessageModel) -> Message:
        """Detach a committed message from persistence.

        Args:
            scope:
                Verified ownership.
            row:
                Owned message.

        Returns:
            Immutable message snapshot.
        """

        return Message(
            id=row.id,
            scope=scope,
            sequence=row.sequence,
            role=cast(Literal["user", "persona"], row.role),
            content=row.content,
            created_at=_utc(row.created_at),
        )

    @staticmethod
    def _attempt(
        scope: ConversationScope, row: GenerationAttemptModel
    ) -> GenerationAttempt:
        """Detach immutable provenance and current recovery status.

        Args:
            scope:
                Verified ownership.
            row:
                Owned ledger row.

        Returns:
            Immutable attempt snapshot.
        """

        return GenerationAttempt(
            id=row.id,
            scope=scope,
            user_message_id=row.user_message_id,
            submitted_input=row.submitted_input,
            generation=EffectiveGeneration.model_validate(row.generation),
            status=cast(AttemptStatus, row.status),
            incomplete_output=row.incomplete_output,
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
            finished_at=(_utc(row.finished_at) if row.finished_at else None),
        )


def _utc(value: datetime) -> datetime:
    """Normalize aware PostgreSQL and naive SQLite timestamps.

    Args:
        value:
            Database timestamp stored in UTC.

    Returns:
        UTC-aware timestamp preserving the original instant.
    """

    return (
        value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    )
