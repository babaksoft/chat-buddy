from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from chat_buddy.chat.domain.chat import ChatRole


@dataclass(slots=True, frozen=True)
class ConversationRecord:
    """Persistence-neutral representation of a conversation."""

    id: UUID
    title: str | None


@dataclass(slots=True, frozen=True)
class MessageRecord:
    """Persistence-neutral representation of a conversation message."""

    id: UUID
    conversation_id: UUID
    role: ChatRole
    content: str


@dataclass(slots=True, frozen=True)
class MemoryRecord:
    """Persistence-neutral representation of a stored memory."""

    id: int
    key: str
    value: str


class ConversationRepository(Protocol):
    """Persistence operations required by conversation services."""

    def create_conversation(
        self,
        title: str | None = None,
    ) -> ConversationRecord:
        """Create and persist a conversation."""

        ...

    def get_conversation(
        self,
        conversation_id: UUID,
    ) -> ConversationRecord | None:
        """Retrieve a conversation by identifier."""

        ...

    def get_conversations(self) -> list[ConversationRecord]:
        """Retrieve all conversations in repository order."""

        ...

    def rename_conversation(
        self,
        conversation_id: UUID,
        title: str,
    ) -> bool:
        """Rename a conversation when it exists."""

        ...

    def delete_conversation(self, conversation_id: UUID) -> bool:
        """Delete a conversation when it exists."""

        ...

    def add_message(
        self,
        conversation_id: UUID,
        role: ChatRole,
        content: str,
    ) -> MessageRecord:
        """Persist a message in a conversation."""

        ...

    def get_messages(self, conversation_id: UUID) -> list[MessageRecord]:
        """Retrieve a conversation's messages in repository order."""

        ...


class MemoryRepository(Protocol):
    """Persistence operations required by memory services."""

    def save_memory(self, key: str, value: str) -> MemoryRecord:
        """Create or update a memory."""

        ...

    def get_memory(self, key: str) -> MemoryRecord | None:
        """Retrieve a memory by key."""

        ...

    def get_memories(self) -> list[MemoryRecord]:
        """Retrieve all memories in repository order."""

        ...

    def delete_memory(self, key: str) -> bool:
        """Delete a memory when it exists."""

        ...
