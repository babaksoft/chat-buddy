import logging

from chat_buddy.application.schemas import (
    ChatRequest,
    ChatResponse,
)
from chat_buddy.application.service.conversation_service import (
    ConversationService,
)
from chat_buddy.application.service.memory_service import (
    MemoryService,
)
from chat_buddy.domain import (
    ChatRole,
    ContextBuilder,
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
        conversation_service: ConversationService,
        memory_service: MemoryService,
        context_builder: ContextBuilder,
        llm_gateway: LLMGateway,
    ) -> None:
        """
        Initialize the service.

        Args:
            conversation_service:
                Conversation management service.

            memory_service:
                Persistent memory service.

            context_builder:
                Context window builder.

            llm_gateway:
                Language model gateway.
        """

        self._conversation_service = conversation_service
        self._memory_service = memory_service
        self._context_builder = context_builder
        self._llm_gateway = llm_gateway

    def chat(
        self,
        request: ChatRequest,
    ) -> ChatResponse:
        """
        Process a chat request.

        Create new conversation if necessary.

        Args:
            request:
                User chat request.

        Returns:
            Assistant response.
        """

        conversation = self._conversation_service.get_or_create_conversation(
            conversation_id=request.conversation_id,
        )
        conversation_id = conversation.id

        logger.info(
            "Processing message for conversation %s.",
            conversation_id,
        )

        self._conversation_service.add_message(
            conversation_id=conversation_id,
            role=ChatRole.USER,
            content=request.message,
        )

        messages = self._conversation_service.get_messages(conversation_id)
        messages = self._memory_service.inject_memories(messages)
        context = self._context_builder.build_context(messages)
        response = self._llm_gateway.generate(context)

        self._conversation_service.add_message(
            conversation_id=conversation_id,
            role=ChatRole.ASSISTANT,
            content=response,
        )

        self._memory_service.extract_memories(messages)

        logger.info(
            "Generated response for conversation %s.",
            conversation_id,
        )

        return ChatResponse(
            conversation_id=conversation_id,
            response=response,
        )
