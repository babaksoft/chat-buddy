from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from chat_buddy.infrastructure.db.models import Memory


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

        memory = self.get_memory(key)

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

        return memory

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

        statement = select(Memory).where(Memory.key == key)

        return self._session.scalar(statement)

    def list_memories(self) -> list[Memory]:
        """
        Return all memories.

        Returns:
            Memories ordered by key.
        """

        statement = select(Memory).order_by(Memory.key)

        return list(self._session.scalars(statement))

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

        memory = self.get_memory(key)

        if memory is None:
            return False

        self._session.delete(memory)
        self._session.commit()

        return True
