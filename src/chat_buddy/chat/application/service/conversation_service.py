import logging
from uuid import UUID

from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    ConversationRecord,
    ConversationRepository,
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

    def get_unmatched_user_message(self, conversation_id: UUID) -> ChatMessage | None:
        """Return the conversation's unmatched final user message, when present.

        Args:
            conversation_id:
                Identifier of the conversation to inspect.

        Returns:
            Unmatched user message, or ``None`` for a closed turn.
        """

        message = self._repository.get_unmatched_user_message(conversation_id)
        if message is None:
            return None
        return ChatMessage(role=message.role, content=message.content)

    def edit_unmatched_user_message(
        self, conversation_id: UUID, content: str
    ) -> ChatMessage:
        """Edit the unmatched tail while no generation attempt is open.

        Args:
            conversation_id:
                Identifier of the conversation containing the tail.
            content:
                Replacement user content.

        Returns:
            Updated user message.
        """

        message = self._repository.edit_unmatched_user_message(conversation_id, content)
        return ChatMessage(role=message.role, content=message.content)

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
