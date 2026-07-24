from __future__ import annotations

from chat_buddy.domain import ChatMessage, ChatRole
from chat_buddy.infrastructure.db.models import Memory
from chat_buddy.infrastructure.db.repositories import MemoryRepository
from chat_buddy.prompts.memory import MEMORY_CONTEXT_HEADER


class MemoryService:
    """Provides application services for persistent memories."""

    def __init__(
        self,
        repository: MemoryRepository,
    ) -> None:
        """
        Initialize the memory service.

        Args:
            repository:
                Repository for persistent memories.
        """

        self._repository = repository

    def save_memory(
        self,
        key: str,
        value: str,
    ) -> Memory:
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

        return self._repository.save_memory(
            key=key,
            value=value,
        )

    def get_memory(
        self,
        key: str,
    ) -> Memory | None:
        """
        Retrieve a memory by key.

        Args:
            key:
                Memory key.

        Returns:
            The matching memory if found; otherwise ``None``.
        """

        return self._repository.get_memory(key)

    def list_memories(self) -> list[Memory]:
        """
        Return all persistent memories.

        Returns:
            A list of all stored memories.
        """

        return self._repository.list_memories()

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
        memories: list[Memory],
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
