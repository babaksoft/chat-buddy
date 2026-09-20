from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from chat_buddy.chat.domain import ExtractedMemory


class _StoredMemory(Protocol):
    """Shape returned by the temporary key/value persistence adapter."""

    @property
    def key(self) -> str:
        """Return the temporary memory key.

        Returns:
            Stable key of the stored prototype memory.
        """

        ...

    @property
    def value(self) -> str:
        """Return the temporary memory value.

        Returns:
            Content of the stored prototype memory.
        """

        ...


class _PrototypeMemoryRepository(Protocol):
    """Application-local compatibility seam removed by later Stage 3 slices."""

    def save_memory(self, key: str, value: str) -> _StoredMemory:
        """Create or replace one temporary key/value memory.

        Args:
            key:
                Stable key of the prototype memory.
            value:
                Content to store for the key.

        Returns:
            Created or updated prototype memory.
        """

        ...

    def get_memory(self, key: str) -> _StoredMemory | None:
        """Return one temporary memory by key.

        Args:
            key:
                Stable key to retrieve.

        Returns:
            Matching prototype memory, or ``None`` when absent.
        """

        ...

    def get_memories(self) -> Sequence[_StoredMemory]:
        """Return all temporary memories in stable order.

        Returns:
            Stored prototype memories in deterministic order.
        """

        ...

    def delete_memory(self, key: str) -> bool:
        """Delete one temporary memory by key.

        Args:
            key:
                Stable key to delete.

        Returns:
            Whether a matching prototype memory was deleted.
        """

        ...


class MemoryService:
    """Provides application services for persistent memories."""

    def __init__(
        self,
        repository: _PrototypeMemoryRepository,
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

        persisted_memories = self._repository.get_memories()

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
