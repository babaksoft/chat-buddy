"""Application boundary for generation-attempt lifecycle management."""

from datetime import datetime
from uuid import UUID

from chat_buddy.chat.domain import (
    GenerationAttemptRecord,
    GenerationAttemptRepository,
    GenerationConfiguration,
    ModelId,
    ProviderId,
)


class GenerationAttemptService:
    """Coordinate generation-attempt creation, transitions, and recovery."""

    def __init__(self, repository: GenerationAttemptRepository) -> None:
        """Initialize the service.

        Args:
            repository:
                Generation-attempt persistence contract.
        """

        self._repository = repository

    def start_generation_attempt(
        self,
        conversation_id: UUID,
        user_content: str,
        provider_id: ProviderId,
        model_id: ModelId,
        effective_configuration: GenerationConfiguration,
    ) -> GenerationAttemptRecord:
        """Atomically persist a user message and pending attempt."""

        return self._repository.start_generation_attempt(
            conversation_id,
            user_content,
            provider_id,
            model_id,
            effective_configuration,
        )

    def retry_generation_attempt(
        self,
        attempt_id: UUID,
        provider_id: ProviderId,
        model_id: ModelId,
        effective_configuration: GenerationConfiguration,
    ) -> GenerationAttemptRecord:
        """Create a pending retry for an incomplete attempt."""

        return self._repository.retry_generation_attempt(
            attempt_id, provider_id, model_id, effective_configuration
        )

    def begin_generation_attempt(
        self, attempt_id: UUID, *, at: datetime
    ) -> GenerationAttemptRecord:
        """Transition a pending attempt to streaming."""

        return self._repository.begin_generation_attempt(attempt_id, at=at)

    def checkpoint_generation_attempt(
        self, attempt_id: UUID, partial_content: str
    ) -> GenerationAttemptRecord:
        """Persist the complete partial output of an active attempt."""

        return self._repository.checkpoint_generation_attempt(
            attempt_id, partial_content
        )

    def complete_generation_attempt(
        self, attempt_id: UUID, assistant_content: str, *, at: datetime
    ) -> GenerationAttemptRecord:
        """Atomically persist an assistant message and complete its attempt."""

        return self._repository.complete_generation_attempt(
            attempt_id, assistant_content, at=at
        )

    def fail_generation_attempt(
        self,
        attempt_id: UUID,
        *,
        error_code: str,
        at: datetime,
        error_detail: str | None = None,
        partial_content: str | None = None,
    ) -> GenerationAttemptRecord:
        """Persist a failed attempt with safe diagnostics."""

        return self._repository.fail_generation_attempt(
            attempt_id,
            error_code=error_code,
            at=at,
            error_detail=error_detail,
            partial_content=partial_content,
        )

    def interrupt_generation_attempt(
        self,
        attempt_id: UUID,
        *,
        at: datetime,
        partial_content: str | None = None,
    ) -> GenerationAttemptRecord:
        """Persist an interrupted attempt."""

        return self._repository.interrupt_generation_attempt(
            attempt_id, at=at, partial_content=partial_content
        )

    def get_generation_attempt(
        self, attempt_id: UUID
    ) -> GenerationAttemptRecord | None:
        """Retrieve one generation attempt by identifier."""

        return self._repository.get_generation_attempt(attempt_id)

    def get_open_generation_attempt(
        self, conversation_id: UUID
    ) -> GenerationAttemptRecord | None:
        """Return the conversation's singular open attempt."""

        return self._repository.get_open_generation_attempt(conversation_id)

    def get_latest_retryable_generation_attempt(
        self, conversation_id: UUID
    ) -> GenerationAttemptRecord | None:
        """Return the singular latest retry target."""

        return self._repository.get_latest_retryable_generation_attempt(conversation_id)

    def get_generation_attempts(
        self, conversation_id: UUID
    ) -> list[GenerationAttemptRecord]:
        """Retrieve all attempts for a conversation in creation order."""

        return self._repository.get_generation_attempts(conversation_id)
