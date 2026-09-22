"""SQLAlchemy persistence for generation-attempt lifecycles."""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from chat_buddy.chat.domain import (
    ChatRole,
    GenerationAttemptRecord,
    GenerationAttemptStatus,
    GenerationConfiguration,
    InvalidGenerationAttemptTransitionError,
    ModelId,
    ProviderId,
)
from chat_buddy.chat.infrastructure.db.models import (
    Conversation,
    GenerationAttempt,
    Message,
)

logger = logging.getLogger(__name__)


class GenerationAttemptRepository:
    """Persist generation attempts and their atomic boundary messages."""

    def __init__(self, session: Session) -> None:
        """Initialize the repository.

        Args:
            session:
                Shared SQLAlchemy session used during the transitional slice.
        """

        self._session = session

    def start_generation_attempt(
        self,
        conversation_id: UUID,
        user_content: str,
        provider_id: ProviderId,
        model_id: ModelId,
        effective_configuration: GenerationConfiguration,
    ) -> GenerationAttemptRecord:
        """Atomically persist a source message and pending attempt."""

        if self._session.get(Conversation, conversation_id) is None:
            raise LookupError(f"Conversation {conversation_id} does not exist.")
        if self._get_unmatched_user_message_id(conversation_id) is not None:
            raise InvalidGenerationAttemptTransitionError(
                "Cannot start a new turn until the unmatched tail completes."
            )

        created_at = datetime.now(UTC)
        message_id = uuid4()
        attempt = GenerationAttemptRecord(
            id=uuid4(),
            conversation_id=conversation_id,
            source_user_message_id=message_id,
            submitted_user_content=user_content,
            provider_id=provider_id,
            model_id=model_id,
            effective_configuration=effective_configuration,
            status=GenerationAttemptStatus.PENDING,
            created_at=created_at,
        )
        try:
            self._session.add(
                Message(
                    id=message_id,
                    conversation_id=conversation_id,
                    role=ChatRole.USER,
                    content=user_content,
                    created_at=created_at,
                )
            )
            self._session.flush()
            self._session.add(self._from_record(attempt))
            self._session.commit()
            return attempt
        except SQLAlchemyError:
            self._session.rollback()
            logger.exception(
                "Failed to start generation attempt for conversation %s.",
                conversation_id,
            )
            raise

    def retry_generation_attempt(
        self,
        attempt_id: UUID,
        provider_id: ProviderId,
        model_id: ModelId,
        effective_configuration: GenerationConfiguration,
    ) -> GenerationAttemptRecord:
        """Create a pending retry reusing an incomplete attempt's source."""

        source = self._get_attempt_model(attempt_id)
        if source.status not in {
            GenerationAttemptStatus.FAILED,
            GenerationAttemptStatus.INTERRUPTED,
        }:
            raise InvalidGenerationAttemptTransitionError(
                "Only a failed or interrupted attempt can be retried."
            )
        latest = self.get_latest_retryable_generation_attempt(source.conversation_id)
        if latest is None or latest.id != source.id:
            raise InvalidGenerationAttemptTransitionError(
                "Only the latest attempt for the unmatched tail can be retried."
            )
        source_message = self._session.get(Message, source.source_user_message_id)
        if source_message is None:
            raise LookupError(
                f"Source message {source.source_user_message_id} does not exist."
            )
        retry = GenerationAttemptRecord(
            id=uuid4(),
            conversation_id=source.conversation_id,
            source_user_message_id=source.source_user_message_id,
            submitted_user_content=source_message.content,
            provider_id=provider_id,
            model_id=model_id,
            effective_configuration=effective_configuration,
            status=GenerationAttemptStatus.PENDING,
            created_at=datetime.now(UTC),
        )
        try:
            self._session.add(self._from_record(retry))
            self._session.commit()
            return retry
        except SQLAlchemyError:
            self._session.rollback()
            logger.exception("Failed to retry generation attempt %s.", attempt_id)
            raise

    def begin_generation_attempt(
        self, attempt_id: UUID, *, at: datetime
    ) -> GenerationAttemptRecord:
        """Transition a pending attempt to streaming."""

        model = self._get_attempt_model(attempt_id)
        return self._persist_update(model, self._to_record(model).start(at=at))

    def checkpoint_generation_attempt(
        self, attempt_id: UUID, partial_content: str
    ) -> GenerationAttemptRecord:
        """Replace the partial content of a streaming attempt."""

        model = self._get_attempt_model(attempt_id)
        return self._persist_update(
            model, self._to_record(model).checkpoint(partial_content)
        )

    def complete_generation_attempt(
        self, attempt_id: UUID, assistant_content: str, *, at: datetime
    ) -> GenerationAttemptRecord:
        """Atomically persist an assistant message and complete its attempt."""

        model = self._get_attempt_model(attempt_id)
        message_id = uuid4()
        updated = self._to_record(model).complete(
            assistant_message_id=message_id, at=at
        )
        try:
            self._session.add(
                Message(
                    id=message_id,
                    conversation_id=updated.conversation_id,
                    role=ChatRole.ASSISTANT,
                    content=assistant_content,
                    created_at=at,
                )
            )
            self._session.flush()
            self._apply_record(model, updated)
            self._session.commit()
            return updated
        except SQLAlchemyError:
            self._session.rollback()
            logger.exception("Failed to complete generation attempt %s.", attempt_id)
            raise

    def fail_generation_attempt(
        self,
        attempt_id: UUID,
        *,
        error_code: str,
        at: datetime,
        error_detail: str | None = None,
        partial_content: str | None = None,
    ) -> GenerationAttemptRecord:
        """Persist a failed terminal state with safe diagnostics."""

        model = self._get_attempt_model(attempt_id)
        updated = self._to_record(model).fail(
            error_code=error_code,
            error_detail=error_detail,
            partial_content=partial_content,
            at=at,
        )
        return self._persist_update(model, updated)

    def interrupt_generation_attempt(
        self,
        attempt_id: UUID,
        *,
        at: datetime,
        partial_content: str | None = None,
    ) -> GenerationAttemptRecord:
        """Persist an interrupted terminal state."""

        model = self._get_attempt_model(attempt_id)
        updated = self._to_record(model).interrupt(
            partial_content=partial_content, at=at
        )
        return self._persist_update(model, updated)

    def get_generation_attempt(
        self, attempt_id: UUID
    ) -> GenerationAttemptRecord | None:
        """Retrieve an attempt by identifier."""

        model = self._session.get(GenerationAttempt, attempt_id)
        return self._to_record(model) if model is not None else None

    def get_open_generation_attempt(
        self, conversation_id: UUID
    ) -> GenerationAttemptRecord | None:
        """Return the singular pending or streaming attempt."""

        statement = (
            select(GenerationAttempt)
            .where(
                GenerationAttempt.conversation_id == conversation_id,
                GenerationAttempt.status.in_(
                    (
                        GenerationAttemptStatus.PENDING,
                        GenerationAttemptStatus.STREAMING,
                    )
                ),
            )
            .order_by(GenerationAttempt.created_at.desc(), GenerationAttempt.id.desc())
            .limit(2)
        )
        models = list(self._session.scalars(statement))
        if len(models) > 1:
            raise RuntimeError(
                f"Conversation {conversation_id} has multiple open attempts."
            )
        return self._to_record(models[0]) if models else None

    def get_latest_retryable_generation_attempt(
        self, conversation_id: UUID
    ) -> GenerationAttemptRecord | None:
        """Return the latest retryable attempt for the unmatched tail."""

        if self.get_open_generation_attempt(conversation_id) is not None:
            return None
        tail_id = self._get_unmatched_user_message_id(conversation_id)
        if tail_id is None:
            return None
        statement = (
            select(GenerationAttempt)
            .where(
                GenerationAttempt.conversation_id == conversation_id,
                GenerationAttempt.source_user_message_id == tail_id,
                GenerationAttempt.status.in_(
                    (
                        GenerationAttemptStatus.FAILED,
                        GenerationAttemptStatus.INTERRUPTED,
                    )
                ),
            )
            .order_by(GenerationAttempt.created_at.desc(), GenerationAttempt.id.desc())
            .limit(1)
        )
        model = self._session.scalar(statement)
        return self._to_record(model) if model is not None else None

    def get_generation_attempts(
        self, conversation_id: UUID
    ) -> list[GenerationAttemptRecord]:
        """Retrieve all attempts for a conversation in creation order."""

        statement = (
            select(GenerationAttempt)
            .where(GenerationAttempt.conversation_id == conversation_id)
            .order_by(GenerationAttempt.created_at.asc())
        )
        return [self._to_record(model) for model in self._session.scalars(statement)]

    def _get_unmatched_user_message_id(self, conversation_id: UUID) -> UUID | None:
        """Return the final message identifier when it is authored by the user."""

        statement = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
        message = self._session.scalar(statement)
        if message is None or message.role is not ChatRole.USER:
            return None
        return message.id

    def _get_attempt_model(self, attempt_id: UUID) -> GenerationAttempt:
        """Load and lock an attempt for a lifecycle transition."""

        statement = (
            select(GenerationAttempt)
            .where(GenerationAttempt.id == attempt_id)
            .with_for_update()
        )
        model = self._session.scalar(statement)
        if model is None:
            raise LookupError(f"Generation attempt {attempt_id} does not exist.")
        return model

    def _persist_update(
        self, model: GenerationAttempt, attempt: GenerationAttemptRecord
    ) -> GenerationAttemptRecord:
        """Apply and commit a validated attempt snapshot."""

        self._apply_record(model, attempt)
        try:
            self._session.commit()
            return attempt
        except SQLAlchemyError:
            self._session.rollback()
            logger.exception("Failed to update generation attempt %s.", attempt.id)
            raise

    @staticmethod
    def _apply_record(
        model: GenerationAttempt, attempt: GenerationAttemptRecord
    ) -> None:
        """Copy mutable lifecycle fields to the persistence model."""

        model.status = attempt.status
        model.started_at = attempt.started_at
        model.finished_at = attempt.finished_at
        model.partial_content = attempt.partial_content
        model.error_code = attempt.error_code
        model.error_detail = attempt.error_detail
        model.assistant_message_id = attempt.assistant_message_id

    @staticmethod
    def _from_record(attempt: GenerationAttemptRecord) -> GenerationAttempt:
        """Translate a domain attempt into a persistence model."""

        return GenerationAttempt(
            id=attempt.id,
            conversation_id=attempt.conversation_id,
            source_user_message_id=attempt.source_user_message_id,
            submitted_user_content=attempt.submitted_user_content,
            provider_id=str(attempt.provider_id),
            model_id=str(attempt.model_id),
            effective_configuration=GenerationAttemptRepository._configuration_to_dict(
                attempt.effective_configuration
            ),
            status=attempt.status,
            partial_content=attempt.partial_content,
            error_code=attempt.error_code,
            error_detail=attempt.error_detail,
            assistant_message_id=attempt.assistant_message_id,
            created_at=attempt.created_at,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
        )

    @staticmethod
    def _to_record(model: GenerationAttempt) -> GenerationAttemptRecord:
        """Translate a persistence model into an immutable domain attempt."""

        created_at = GenerationAttemptRepository._timezone_aware(model.created_at)
        if created_at is None:
            raise ValueError("Persisted generation attempt has no creation time.")
        return GenerationAttemptRecord(
            id=model.id,
            conversation_id=model.conversation_id,
            source_user_message_id=model.source_user_message_id,
            submitted_user_content=model.submitted_user_content,
            provider_id=ProviderId(model.provider_id),
            model_id=ModelId(model.model_id),
            effective_configuration=(
                GenerationAttemptRepository._configuration_from_dict(
                    model.effective_configuration
                )
            ),
            status=model.status,
            partial_content=model.partial_content,
            error_code=model.error_code,
            error_detail=model.error_detail,
            assistant_message_id=model.assistant_message_id,
            created_at=created_at,
            started_at=GenerationAttemptRepository._timezone_aware(model.started_at),
            finished_at=GenerationAttemptRepository._timezone_aware(model.finished_at),
        )

    @staticmethod
    def _configuration_to_dict(
        configuration: GenerationConfiguration,
    ) -> dict[str, Any]:
        """Serialize provider-neutral generation configuration."""

        return {
            "temperature": configuration.temperature,
            "top_p": configuration.top_p,
            "max_output_tokens": configuration.max_output_tokens,
            "seed": configuration.seed,
        }

    @staticmethod
    def _configuration_from_dict(values: dict[str, Any]) -> GenerationConfiguration:
        """Deserialize provider-neutral generation configuration."""

        return GenerationConfiguration(
            temperature=values.get("temperature"),
            top_p=values.get("top_p"),
            max_output_tokens=values.get("max_output_tokens"),
            seed=values.get("seed"),
        )

    @staticmethod
    def _timezone_aware(value: datetime | None) -> datetime | None:
        """Normalize SQLite-naive timestamps to UTC."""

        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)
