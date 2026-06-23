from chat_buddy.application.schemas import (
    ConversationSummary,
)
from chat_buddy.infrastructure.db.repositories import (
    ConversationRepository,
)


class ConversationService:
    """
    Coordinate conversation-related operations.
    """

    def __init__(
        self,
        repository: ConversationRepository,
    ) -> None:
        self._repository = repository

    def list_conversations(
        self,
    ) -> list[ConversationSummary]:
        """
        Retrieve all conversations.

        Returns:
            Conversation summaries ordered by
            most recently updated first.
        """

        conversations = self._repository.list_conversations()

        return [
            ConversationSummary(
                id=conversation.id,
                title=conversation.title,
            )
            for conversation in conversations
        ]

    def new_conversation(
        self,
    ) -> ConversationSummary:
        """
        Create a new conversation.

        Returns:
            Newly created conversation.
        """

        conversation = self._repository.create_conversation()
        return ConversationSummary(
            id=conversation.id,
            title=conversation.title,
        )
