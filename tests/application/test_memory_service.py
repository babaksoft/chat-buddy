from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from chat_buddy.chat.application.config import MemoryConfig
from chat_buddy.chat.application.service import MemoryService
from chat_buddy.chat.domain import ChatMessage, ChatRole
from chat_buddy.chat.prompts.memory import MEMORY_CONTEXT_HEADER


@dataclass(slots=True, frozen=True)
class StoredMemory:
    """Temporary in-memory record used by the compatibility service tests."""

    id: int
    key: str
    value: str


class FakeMemoryRepository:
    """In-memory implementation of the memory repository contract."""

    def __init__(self) -> None:
        """Initialize an empty in-memory prototype store."""

        self._memories: dict[str, StoredMemory] = {}

    def save_memory(self, key: str, value: str) -> StoredMemory:
        """Create or replace one prototype memory.

        Args:
            key:
                Stable memory key.
            value:
                Memory content to store.

        Returns:
            Created or updated stored memory.
        """

        memory = StoredMemory(
            id=len(self._memories) + 1,
            key=key,
            value=value,
        )
        self._memories[key] = memory
        return memory

    def get_memory(self, key: str) -> StoredMemory | None:
        """Return one prototype memory by key.

        Args:
            key:
                Stable memory key.

        Returns:
            Matching memory, or ``None`` when absent.
        """

        return self._memories.get(key)

    def get_memories(self) -> list[StoredMemory]:
        """Return all prototype memories in stable key order.

        Returns:
            Stored memories ordered by key.
        """

        return [self._memories[key] for key in sorted(self._memories)]

    def delete_memory(self, key: str) -> bool:
        """Delete one prototype memory by key.

        Args:
            key:
                Stable memory key.

        Returns:
            Whether a matching memory was deleted.
        """

        return self._memories.pop(key, None) is not None


@pytest.fixture
def service() -> MemoryService:
    """Create a memory service instance for testing.

    Returns:
        Configured memory service.
    """

    return MemoryService(
        repository=FakeMemoryRepository(),
        llm_gateway=Mock(),
        config=MemoryConfig(extraction_interval=10),
    )


def test_inject_memories_returns_original_messages_when_empty(
    service: MemoryService,
) -> None:
    """Verify empty memory store leaves messages unchanged.

    Args:
        service:
            Memory service under test.
    """

    messages = [
        ChatMessage(
            role=ChatRole.USER,
            content="Hello",
        ),
    ]

    result = service.inject_memories(messages)

    assert result is messages


def test_inject_memories_prepends_system_message(
    service: MemoryService,
) -> None:
    """Verify stored memories are injected as a system message.

    Args:
        service:
            Memory service under test.
    """

    service.save_memory(
        key="favorite_language",
        value="Python",
    )

    messages = [
        ChatMessage(
            role=ChatRole.USER,
            content="Hello",
        ),
    ]

    result = service.inject_memories(messages)

    assert len(result) == 2
    assert result[0].role == ChatRole.SYSTEM
    assert MEMORY_CONTEXT_HEADER in result[0].content
    assert "- favorite_language: Python" in result[0].content
    assert result[1:] == messages


def test_inject_memories_formats_multiple_memories(
    service: MemoryService,
) -> None:
    """Verify multiple memories are included in context.

    Args:
        service:
            Memory service under test.
    """

    service.save_memory(
        key="city",
        value="Tehran",
    )
    service.save_memory(
        key="editor",
        value="VS Code",
    )

    result = service.inject_memories([])

    assert len(result) == 1
    assert "- city: Tehran" in result[0].content
    assert "- editor: VS Code" in result[0].content


def test_format_memories_for_context(
    service: MemoryService,
) -> None:
    """Verify private formatter produces expected output.

    Args:
        service:
            Memory service under test.
    """

    memory = Mock()
    memory.key = "favorite_language"
    memory.value = "Python"

    formatted = service._format_memories_for_context([memory])

    assert formatted == f"{MEMORY_CONTEXT_HEADER}\n\n- favorite_language: Python"
