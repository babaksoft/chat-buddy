import logging
from datetime import datetime
from uuid import UUID

from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    ConversationRecord,
    ConversationRepository,
    GenerationAttemptRecord,
    GenerationConfiguration,
    ModelId,
    ProviderId,
)

logger = logging.getLogger(__name__)


class ConversationService:
    """
    Coordinate conversation-related operations.
    """

    def __init__(
        self,
        repository: ConversationRepository,
    ) -> None:
        """
        Initialize the conversation service.

        Args:
            repository:
                Conversation repository.
        """

        self._repository = repository

    def get_conversations(
        self,
    ) -> list[ConversationRecord]:
        """
        Retrieve all conversations.

        Returns:
            Conversation records ordered by
            most recently updated first.
        """

        return self._repository.get_conversations()

    def create_conversation(
        self,
    ) -> ConversationRecord:
        """
        Create a new conversation.

        Returns:
            Newly created conversation.
        """

        return self._repository.create_conversation()

    def rename_conversation(
        self,
        conversation_id: UUID,
        title: str,
    ) -> bool:
        """
        Renames an existing conversation.

        Args:
            conversation_id:
                Unique conversation identifier.
            title:
                New conversation title.

        Returns:
            True if the conversation was renamed, otherwise False.
        """

        cleaned = title.strip()
        if not cleaned:
            raise ValueError("Title cannot include only whitespace characters.")

        cleaned = self._auto_ellipsis(" ".join(cleaned.split()))

        return self._repository.rename_conversation(
            conversation_id=conversation_id,
            title=cleaned,
        )

    def delete_conversation(
        self,
        conversation_id: UUID,
    ) -> bool:
        """
        Delete a conversation and all associated messages.

        Args:
            conversation_id:
                Unique conversation identifier.

        Returns:
            True if the conversation was deleted, otherwise False.
        """

        return self._repository.delete_conversation(
            conversation_id=conversation_id,
        )

    def get_or_create_conversation(
        self, conversation_id: UUID | None
    ) -> ConversationRecord:
        """
        Retrieves a conversation by identifier.

        Creates a new conversation if no conversation
        with given identifier exists.

        Args:
            conversation_id:
                Optional conversation identifier.
        """

        if conversation_id:
            persisted = self._repository.get_conversation(conversation_id)
            conversation = persisted or self._repository.create_conversation()
        else:
            conversation = self._repository.create_conversation()

        return conversation

    def get_conversation(self, conversation_id: UUID) -> ConversationRecord | None:
        """Retrieve a conversation without creating a replacement.

        Args:
            conversation_id:
                Identifier of the conversation to retrieve.

        Returns:
            The matching conversation, or ``None`` when it does not exist.
        """

        return self._repository.get_conversation(conversation_id)

    def update_generation_defaults(
        self,
        conversation_id: UUID,
        provider_id: ProviderId,
        model_id: ModelId,
        requested_configuration: GenerationConfiguration,
    ) -> ConversationRecord | None:
        """Persist defaults for the conversation's next generation attempt.

        Args:
            conversation_id:
                Identifier of the conversation to update.
            provider_id:
                Selected response provider.
            model_id:
                Selected provider-local model.
            requested_configuration:
                Provider-neutral requested generation values.

        Returns:
            Updated conversation, or ``None`` when it does not exist.
        """

        return self._repository.update_generation_defaults(
            conversation_id,
            provider_id,
            model_id,
            requested_configuration,
        )

    def start_generation_attempt(
        self,
        conversation_id: UUID,
        user_content: str,
        provider_id: ProviderId,
        model_id: ModelId,
        effective_configuration: GenerationConfiguration,
    ) -> GenerationAttemptRecord:
        """Atomically persist a user message and pending generation attempt.

        Args:
            conversation_id:
                Identifier of the target conversation.
            user_content:
                Source user-message content.
            provider_id:
                Effective response provider.
            model_id:
                Effective provider-local model.
            effective_configuration:
                Validated immutable generation settings.

        Returns:
            Newly persisted pending generation attempt.
        """

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
        """Create a pending retry for an incomplete generation attempt.

        Args:
            attempt_id:
                Identifier of the failed or interrupted attempt.
            provider_id:
                Effective response provider for the retry.
            model_id:
                Effective provider-local model for the retry.
            effective_configuration:
                Validated immutable generation settings for the retry.

        Returns:
            Newly persisted pending retry attempt.
        """

        return self._repository.retry_generation_attempt(
            attempt_id,
            provider_id,
            model_id,
            effective_configuration,
        )

    def begin_generation_attempt(
        self,
        attempt_id: UUID,
        *,
        at: datetime,
    ) -> GenerationAttemptRecord:
        """Transition a pending generation attempt to streaming.

        Args:
            attempt_id:
                Identifier of the pending attempt.
            at:
                Time response generation started.

        Returns:
            Persisted streaming generation attempt.
        """

        return self._repository.begin_generation_attempt(attempt_id, at=at)

    def complete_generation_attempt(
        self,
        attempt_id: UUID,
        assistant_content: str,
        *,
        at: datetime,
    ) -> GenerationAttemptRecord:
        """Atomically persist an assistant message and complete its attempt.

        Args:
            attempt_id:
                Identifier of the streaming attempt.
            assistant_content:
                Completed assistant response.
            at:
                Time response generation completed.

        Returns:
            Persisted completed generation attempt.
        """

        return self._repository.complete_generation_attempt(
            attempt_id,
            assistant_content,
            at=at,
        )

    def checkpoint_generation_attempt(
        self, attempt_id: UUID, partial_content: str
    ) -> GenerationAttemptRecord:
        """Persist the complete partial output accumulated by an active attempt.

        Args:
            attempt_id:
                Identifier of the streaming attempt.
            partial_content:
                Complete partial response accumulated so far.

        Returns:
            Updated streaming attempt.
        """

        return self._repository.checkpoint_generation_attempt(
            attempt_id, partial_content
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
        """Persist a failed generation attempt.

        Args:
            attempt_id:
                Identifier of the streaming attempt.
            error_code:
                Stable normalized failure code.
            at:
                Time generation failed.
            error_detail:
                Optional safe user-facing failure detail.
            partial_content:
                Optional complete partial response.

        Returns:
            Persisted failed attempt.
        """

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
        """Persist an interrupted generation attempt.

        Args:
            attempt_id:
                Identifier of the streaming attempt.
            at:
                Time generation was interrupted.
            partial_content:
                Optional complete partial response.

        Returns:
            Persisted interrupted attempt.
        """

        return self._repository.interrupt_generation_attempt(
            attempt_id,
            at=at,
            partial_content=partial_content,
        )

    def get_generation_attempt(
        self, attempt_id: UUID
    ) -> GenerationAttemptRecord | None:
        """Retrieve a generation attempt by identifier.

        Args:
            attempt_id:
                Identifier of the attempt to retrieve.

        Returns:
            Matching attempt, or ``None`` when it does not exist.
        """

        return self._repository.get_generation_attempt(attempt_id)

    def get_unresolved_generation_attempts(
        self, conversation_id: UUID
    ) -> list[GenerationAttemptRecord]:
        """Retrieve pending and streaming attempts for a conversation.

        Args:
            conversation_id:
                Identifier of the conversation to inspect.

        Returns:
            Unresolved attempts ordered from oldest to newest.
        """

        return self._repository.get_unresolved_generation_attempts(conversation_id)

    def get_message(self, message_id: UUID) -> ChatMessage | None:
        """Retrieve one message by identifier.

        Args:
            message_id:
                Identifier of the message to retrieve.

        Returns:
            Matching application message, or ``None`` when absent.
        """

        message = self._repository.get_message(message_id)
        if message is None:
            return None

        return ChatMessage(role=message.role, content=message.content)

    def add_message(
        self, conversation_id: UUID, role: ChatRole, content: str
    ) -> ChatMessage:
        """
        Add a message to an existing conversation.

        Args:
            conversation_id:
                Target conversation identifier.
            role:
                Role of the message author.
            content:
                Message text content.

        Returns:
            The newly created message.
        """

        message = self._repository.add_message(
            conversation_id=conversation_id,
            role=role,
            content=content,
        )

        return ChatMessage(
            role=message.role,
            content=message.content,
        )

    def get_messages(self, conversation_id: UUID) -> list[ChatMessage]:
        """
        Retrieve messages in a conversation.

        Args:
            conversation_id:
                Unique conversation identifier.

        Returns:
            List of conversation messages ordered
            from oldest to newest.
        """

        messages = self._repository.get_messages(conversation_id=conversation_id)

        return [
            ChatMessage(
                role=ChatRole(message.role.value),
                content=message.content,
            )
            for message in messages
        ]

    def _auto_ellipsis(self, text: str) -> str:
        """
        Clip given text and append ellipsis, if necessary

        Args:
            text:
                Given text.

        Returns:
            Original text if it has 50 characters or less,
            otherwise clipped text ending with ellipsis.
        """

        clipped = text
        if len(clipped) > 50:
            clipped = clipped[:47].rstrip()
            clipped = f"{clipped}..."

        return clipped
