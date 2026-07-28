from __future__ import annotations

import logging
from uuid import UUID

from chat_buddy.application.schemas import (
    ChatRequest,
    ChatResponse,
)
from chat_buddy.application.service.conversation_service import ConversationService
from chat_buddy.application.service.memory_service import MemoryService
from chat_buddy.domain import ChatMessage, ChatRole, ContextBuilder, LLMGateway

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
        is_first_exchange = len(messages) == 1
        messages = self._memory_service.inject_memories(messages)
        context = self._context_builder.build_context(messages)
        response = self._llm_gateway.generate(context)

        self._conversation_service.add_message(
            conversation_id=conversation_id,
            role=ChatRole.ASSISTANT,
            content=response,
        )

        self._memory_service.extract_memories(messages)

        if is_first_exchange and not conversation.title:
            self._title_conversation(
                conversation_id=conversation_id,
                user_message=request.message,
                assistant_message=response,
            )

        logger.info(
            "Generated response for conversation %s.",
            conversation_id,
        )

        return ChatResponse(
            conversation_id=conversation_id,
            response=response,
        )

    def _title_conversation(
        self,
        conversation_id: UUID,
        user_message: str,
        assistant_message: str,
    ) -> None:
        """
        Generate and persist a title for a first exchange.

        Args:
            conversation_id:
                Unique conversation identifier.

            user_message:
                First user message in the conversation.

            assistant_message:
                Assistant reply for the first exchange.
        """

        title = ""

        try:
            title = self._sanitize_title(
                self._llm_gateway.generate_title(
                    [
                        ChatMessage(
                            role=ChatRole.USER,
                            content=user_message,
                        ),
                        ChatMessage(
                            role=ChatRole.ASSISTANT,
                            content=assistant_message,
                        ),
                    ]
                )
            )
        except Exception:
            logger.exception(
                "Failed to generate title for conversation %s.",
                conversation_id,
            )

        if not title:
            title = self._build_fallback_title(user_message)

        try:
            updated = self._conversation_service.rename_conversation(
                conversation_id=conversation_id,
                title=title,
            )

            if updated:
                logger.info(
                    "Set conversation %s title to '%s'.",
                    conversation_id,
                    title,
                )
            else:
                logger.warning(
                    "Conversation %s title was not updated.",
                    conversation_id,
                )

        except Exception:
            logger.exception(
                "Failed to persist conversation title for %s.",
                conversation_id,
            )

    def _sanitize_title(
        self,
        title: str,
    ) -> str:
        """
        Normalize a generated title for persistence.

        Args:
            title:
                Generated title text.

        Returns:
            Cleaned title text.
        """

        cleaned = title.replace("\n", " ").strip()
        cleaned = cleaned.strip('"').strip("'").strip()
        cleaned = " ".join(cleaned.split())

        return self._auto_ellipsis(cleaned)

    def _build_fallback_title(
        self,
        user_message: str,
    ) -> str:
        """
        Build a deterministic fallback title.

        Args:
            user_message:
                First user message in the conversation.

        Returns:
            Fallback title text.
        """

        cleaned = " ".join(user_message.split()).strip('"').strip("'")

        if not cleaned:
            return "New conversation"

        return self._auto_ellipsis(cleaned)

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
