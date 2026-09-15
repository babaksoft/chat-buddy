from unittest.mock import Mock

import pytest

from chat_buddy.chat.application.config import MemoryConfig
from chat_buddy.chat.application.service import MemoryService
from chat_buddy.chat.domain import ChatMessage, ChatRole, MemoryRecord
from chat_buddy.chat.prompts.memory import MEMORY_CONTEXT_HEADER


class FakeMemoryRepository:
    """In-memory implementation of the memory repository contract."""

    def __init__(self) -> None:
        self._memories: dict[str, MemoryRecord] = {}

    def save_memory(self, key: str, value: str) -> MemoryRecord:
        memory = MemoryRecord(
            id=len(self._memories) + 1,
            key=key,
            value=value,
        )
        self._memories[key] = memory
        return memory

    def get_memory(self, key: str) -> MemoryRecord | None:
        return self._memories.get(key)

    def get_memories(self) -> list[MemoryRecord]:
        return [self._memories[key] for key in sorted(self._memories)]

    def delete_memory(self, key: str) -> bool:
        return self._memories.pop(key, None) is not None


@pytest.fixture
def service() -> MemoryService:
    """
    Create a memory service instance for testing.

    Args:
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
    """Verify empty memory store leaves messages unchanged."""

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
    """Verify stored memories are injected as a system message."""

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
    """Verify multiple memories are included in context."""

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
    """Verify private formatter produces expected output."""

    memory = Mock()
    memory.key = "favorite_language"
    memory.value = "Python"

    formatted = service._format_memories_for_context([memory])

    assert formatted == f"{MEMORY_CONTEXT_HEADER}\n\n- favorite_language: Python"
