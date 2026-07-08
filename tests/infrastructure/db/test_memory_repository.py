import pytest
from sqlalchemy.orm import Session

from chat_buddy.infrastructure.db.repositories import MemoryRepository


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


def test_save_memory_creates_new_memory(repository: MemoryRepository) -> None:
    """Verify new memory is correctly created."""

    memory = repository.save_memory(
        "favorite_language",
        "Python",
    )

    assert memory.id is not None
    assert memory.key == "favorite_language"
    assert memory.value == "Python"


def test_save_memory_updates_existing_memory(repository: MemoryRepository) -> None:
    """Verify existing memory is correctly updated."""

    repository.save_memory(
        "favorite_language",
        "Python",
    )

    updated = repository.save_memory(
        "favorite_language",
        "C#",
    )

    assert updated.value == "C#"

    memories = repository.list_memories()
    assert len(memories) == 1


def test_get_memory_returns_existing_memory(repository: MemoryRepository) -> None:
    """Verify existing memory is correctly retrieved."""

    repository.save_memory(
        "editor",
        "PyCharm",
    )

    memory = repository.get_memory("editor")

    assert memory is not None
    assert memory.value == "PyCharm"


def test_get_memory_returns_none_when_missing(repository: MemoryRepository) -> None:
    """Verify non-existing memory is correctly handled."""

    memory = repository.get_memory("missing")

    assert memory is None


def test_list_memories_returns_all_memories(repository: MemoryRepository) -> None:
    """Verify all memory items can be retrieved."""

    repository.save_memory("b", "2")
    repository.save_memory("a", "1")

    memories = repository.list_memories()

    assert len(memories) == 2
    assert [m.key for m in memories] == [
        "a",
        "b",
    ]


def test_delete_memory_removes_existing_memory(repository: MemoryRepository) -> None:
    """Verify existing memory is correctly deleted."""

    repository.save_memory(
        "city",
        "London",
    )

    deleted = repository.delete_memory("city")

    assert deleted is True
    assert repository.get_memory("city") is None


def test_delete_memory_returns_false_when_missing(repository: MemoryRepository) -> None:
    """Verify deleting non-existing memory is correctly handled."""

    deleted = repository.delete_memory("missing")

    assert deleted is False
