import logging
from uuid import UUID

from chat_buddy.application.schemas import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatRole,
)
from chat_buddy.infrastructure.db.models import (
    MessageRole,
)
from chat_buddy.infrastructure.db.repositories import (
    ConversationRepository,
)
from chat_buddy.infrastructure.llm.base import (
    LLMGateway,
)

logger = logging.getLogger(__name__)


class ChatService:
    """
    Coordinate chat interactions between persistence
    and language model layers.
    """

    def __init__(
        self,
        repository: ConversationRepository,
        llm_gateway: LLMGateway,
    ) -> None:
        """
        Initialize the service.

        Args:
            repository:
                Conversation repository.

            llm_gateway:
                Language model gateway.
        """

        self._repository = repository
        self._llm_gateway = llm_gateway

    def chat(
        self,
        request: ChatRequest,
    ) -> ChatResponse:
        """
        Process a chat request. Create new conversation if necessary.

        Args:
            request:
                User chat request.

        Returns:
            Assistant response.
        """

        if request.conversation_id is None:
            conversation = self._repository.create_conversation()
            conversation_id = conversation.id
        else:
            conversation_id = request.conversation_id

        logger.info(
            "Processing message for conversation %s.",
            conversation_id,
        )

        self._repository.add_message(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=request.message,
        )

        response_text = self._llm_gateway.generate(
            request.message,
        )

        self._repository.add_message(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=response_text,
        )

        logger.info(
            "Generated response for conversation %s.",
            conversation_id,
        )

        return ChatResponse(
            conversation_id=conversation_id,
            response=response_text,
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

        db_messages = self._repository.get_messages(conversation_id=conversation_id)

        return [
            ChatMessage(
                role=ChatRole(msg.role.value),
                content=msg.content,
            )
            for msg in db_messages
        ]
