import logging
from uuid import UUID

from chat_buddy.application.memory_service import MemoryService
from chat_buddy.application.schemas import (
    ChatRequest,
    ChatResponse,
)
from chat_buddy.domain import (
    ChatMessage,
    ChatRole,
    ContextBuilder,
    LLMGateway,
)
from chat_buddy.infrastructure.config import settings
from chat_buddy.infrastructure.db.repositories import (
    ConversationRepository,
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
        context_builder: ContextBuilder,
        llm_gateway: LLMGateway,
        memory_service: MemoryService,
    ) -> None:
        """
        Initialize the service.

        Args:
            repository:
                Conversation repository.

            context_builder:
                Context window builder.

            llm_gateway:
                Language model gateway.

            memory_service:
                Persistent memory service.
        """

        self._repository = repository
        self._context_builder = context_builder
        self._llm_gateway = llm_gateway
        self._memory_service = memory_service

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
            role=ChatRole.USER,
            content=request.message,
        )

        messages = self.get_messages(conversation_id)
        messages = self._memory_service.inject_memories(messages)
        context = self._context_builder.build_context(messages)
        response = self._llm_gateway.generate(context)

        self._repository.add_message(
            conversation_id=conversation_id,
            role=ChatRole.ASSISTANT,
            content=response,
        )

        self._extract_memories(messages)

        logger.info(
            "Generated response for conversation %s.",
            conversation_id,
        )

        return ChatResponse(
            conversation_id=conversation_id,
            response=response,
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

    def _should_extract_memories(
        self,
        messages: list[ChatMessage],
    ) -> bool:
        """
        Determine whether memories should be extracted.

        Args:
            messages:
                Conversation history.

        Returns:
            True if memory extraction should be performed.
        """

        user_turns = sum(1 for message in messages if message.role is ChatRole.USER)

        return user_turns > 0 and user_turns % settings.MEMORY_EXTRACTION_INTERVAL == 0

    def _extract_memories(
        self,
        messages: list[ChatMessage],
    ) -> None:
        """
        Extract and persist long-term memories.

        Args:
            messages:
                Conversation history.
        """

        if not self._should_extract_memories(messages):
            return

        memories = self._llm_gateway.extract_memories(messages)
        for memory in memories:
            self._memory_service.save_memory(
                key=memory.key,
                value=memory.value,
            )

        logger.info(
            "Memory extraction completed: extracted=%d persisted=%d",
            len(memories),
            len(memories),
        )
