import logging
from uuid import UUID

from chat_buddy.application.schemas import (
    ConversationEntry,
)
from chat_buddy.domain import ChatMessage, ChatRole
from chat_buddy.infrastructure.db.repositories import (
    ConversationRepository,
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
    ) -> list[ConversationEntry]:
        """
        Retrieve all conversations.

        Returns:
            Conversation entries ordered by
            most recently updated first.
        """

        conversations = self._repository.get_conversations()

        return [
            ConversationEntry(
                id=conversation.id,
                title=conversation.title,
            )
            for conversation in conversations
        ]

    def create_conversation(
        self,
    ) -> ConversationEntry:
        """
        Create a new conversation.

        Returns:
            Newly created conversation.
        """

        conversation = self._repository.create_conversation()
        return ConversationEntry(
            id=conversation.id,
            title=conversation.title,
        )

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

    def get_or_create_conversation(
        self, conversation_id: UUID | None
    ) -> ConversationEntry:
        """
        Retrieves a conversation by identifier.

        Creates a new conversation if no conversation
        with given identifier exists.
        """

        if conversation_id:
            persisted = self._repository.get_conversation(conversation_id)
            conversation = persisted or self._repository.create_conversation()
        else:
            conversation = self._repository.create_conversation()

        return ConversationEntry(
            id=conversation.id,
            title=conversation.title,
        )

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
