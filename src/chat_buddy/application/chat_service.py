import logging
from uuid import uuid4

from chat_buddy.application.schemas import (
    ChatRequest,
    ChatResponse,
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
        Process a chat request.

        Args:
            request:
                User chat request.

        Returns:
            Assistant response.
        """

        logger.info(
            "Processing message for conversation %s.",
            request.conversation_id,
        )

        self._repository.add_message(
            conversation_id=request.conversation_id,
            role=MessageRole.USER,
            content=request.message,
        )

        response_text = self._llm_gateway.generate(
            request.message,
        )

        self._repository.add_message(
            conversation_id=request.conversation_id,
            role=MessageRole.ASSISTANT,
            content=response_text,
        )

        logger.info(
            "Generated response for conversation %s.",
            request.conversation_id,
        )

        # Temporary patch until we ensure conversation exists
        return ChatResponse(
            conversation_id=request.conversation_id or uuid4(),
            response=response_text,
        )
