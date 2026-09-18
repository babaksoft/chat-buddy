from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from chat_buddy.chat.infrastructure.db.models import Memory


@dataclass(slots=True, frozen=True)
class StoredMemory:
    """Temporary key/value adapter result used until the Stage 3 migration."""

    id: int
    key: str
    value: str


class MemoryRepository:
    """Provides persistence operations for memories."""

    def __init__(self, session: Session) -> None:
        """
        Initialize the repository.

        Args:
            session: SQLAlchemy session.
        """

        self._session = session

    def save_memory(
        self,
        key: str,
        value: str,
    ) -> StoredMemory:
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

        memory = self._get_memory_model(key)

        if memory is None:
            memory = Memory(
                key=key,
                value=value,
            )
            self._session.add(memory)
        else:
            memory.value = value

        self._session.commit()
        self._session.refresh(memory)

        return self._to_record(memory)

    def get_memory(
        self,
        key: str,
    ) -> StoredMemory | None:
        """
        Retrieve a memory by key.

        Args:
            key:
                Memory key.

        Returns:
            The matching memory if found; otherwise ``None``.
        """

        memory = self._get_memory_model(key)

        if memory is None:
            return None

        return self._to_record(memory)

    def get_memories(self) -> list[StoredMemory]:
        """
        Return all memories.

        Returns:
            Memories ordered by key.
        """

        statement = select(Memory).order_by(Memory.key)

        return [self._to_record(item) for item in self._session.scalars(statement)]

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
            ``True`` if a memory was deleted, otherwise ``False``.
        """

        memory = self._get_memory_model(key)

        if memory is None:
            return False

        self._session.delete(memory)
        self._session.commit()

        return True

    def _get_memory_model(self, key: str) -> Memory | None:
        """Retrieve the persistence model used for adapter operations.

        Args:
            key:
                Prototype memory key to retrieve.

        Returns:
            Matching persistence model, or ``None`` when absent.
        """

        statement = select(Memory).where(Memory.key == key)

        return self._session.scalar(statement)

    @staticmethod
    def _to_record(memory: Memory) -> StoredMemory:
        """Translate a persistence model into a compatibility record.

        Args:
            memory:
                Prototype persistence model to translate.

        Returns:
            Immutable adapter result for the application compatibility seam.
        """

        return StoredMemory(
            id=memory.id,
            key=memory.key,
            value=memory.value,
        )
