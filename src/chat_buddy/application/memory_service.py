from __future__ import annotations

import logging

from chat_buddy.domain import (
    ChatMessage,
    ChatRole,
    ExtractedMemory,
    LLMGateway,
)
from chat_buddy.infrastructure.config import settings
from chat_buddy.infrastructure.db.repositories import MemoryRepository
from chat_buddy.infrastructure.llm import OllamaGateway
from chat_buddy.prompts.memory import MEMORY_CONTEXT_HEADER

logger = logging.getLogger(__name__)


class MemoryService:
    """Provides application services for persistent memories."""

    def __init__(
        self,
        repository: MemoryRepository,
        llm_gateway: LLMGateway | None = None,
    ) -> None:
        """
        Initialize the memory service.

        Args:
            repository:
                Repository for persistent memories.

            llm_gateway:
                LLM Gateway used for memory extraction.
        """

        self._repository = repository
        self._llm_gateway = llm_gateway or OllamaGateway()

    def save_memory(
        self,
        key: str,
        value: str,
    ) -> ExtractedMemory:
        """
        Create or update a memory.

        Args:
            key:
                Memory key.

            value:
                Memory value.

        Returns:
            The persisted memory.
        """

        persisted_memory = self._repository.save_memory(
            key=key,
            value=value,
        )

        return ExtractedMemory(
            key=persisted_memory.key,
            value=persisted_memory.value,
        )

    def get_memory(
        self,
        key: str,
    ) -> ExtractedMemory | None:
        """
        Retrieve a memory by key.

        Args:
            key:
                Memory key.

        Returns:
            The matching memory if found; otherwise ``None``.
        """

        persisted_memory = self._repository.get_memory(key)
        if persisted_memory:
            return ExtractedMemory(
                key=persisted_memory.key,
                value=persisted_memory.value,
            )

        return None

    def list_memories(self) -> list[ExtractedMemory]:
        """
        Return all persistent memories.

        Returns:
            A list of all stored memories.
        """

        persisted_memories = self._repository.list_memories()

        return [
            ExtractedMemory(key=memory.key, value=memory.value)
            for memory in persisted_memories
        ]

    def delete_memory(
        self,
        key: str,
    ) -> bool:
        """
        Delete a memory.

        Args:
            key:
                Memory key.

        Returns:
            ``True`` if the memory existed and was deleted; otherwise ``False``.
        """

        return self._repository.delete_memory(key)

    def extract_memories(
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
            self.save_memory(
                key=memory.key,
                value=memory.value,
            )

        logger.info(
            "Memory extraction completed: extracted=%d persisted=%d",
            len(memories),
            len(memories),
        )

    def inject_memories(
        self,
        messages: list[ChatMessage],
    ) -> list[ChatMessage]:
        """
        Prepend persisted memories to conversation messages.

        Args:
            messages:
                Conversation history.

        Returns:
            Messages with a leading system message when
            memories exist; otherwise the original list.
        """

        memories = self.list_memories()

        if not memories:
            return messages

        return [
            ChatMessage(
                role=ChatRole.SYSTEM,
                content=self._format_memories_for_context(memories),
            ),
            *messages,
        ]

    def _format_memories_for_context(
        self,
        memories: list[ExtractedMemory],
    ) -> str:
        """
        Format persisted memories for model context.

        Args:
            memories:
                Stored memories.

        Returns:
            Formatted memory context.
        """

        lines = [f"- {memory.key}: {memory.value}" for memory in memories]

        return f"{MEMORY_CONTEXT_HEADER}\n\n" + "\n".join(lines)

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
