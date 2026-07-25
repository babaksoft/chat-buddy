from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from chat_buddy.application.service import MemoryService
from chat_buddy.domain import ChatMessage, ChatRole
from chat_buddy.infrastructure.db.repositories import MemoryRepository
from chat_buddy.prompts.memory import MEMORY_CONTEXT_HEADER


@pytest.fixture
def repository(
    session: Session,
) -> MemoryRepository:
    """
    Create a repository instance for testing.

    Args:
        session:
            Test database session.

    Returns:
        Repository connected to the test database.
    """

    return MemoryRepository(session)


@pytest.fixture
def service(
    repository: MemoryRepository,
) -> MemoryService:
    """
    Create a memory service instance for testing.

    Args:
        repository:
            Memory repository.

    Returns:
        Configured memory service.
    """

    return MemoryService(
        repository=repository,
        llm_gateway=Mock(),
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
