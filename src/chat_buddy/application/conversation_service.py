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

        conversations = self._repository.list_conversations()

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
