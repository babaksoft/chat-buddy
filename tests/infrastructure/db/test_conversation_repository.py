import pytest
from sqlalchemy.orm import Session

from chat_buddy.infrastructure.db.models import (
    MessageRole,
)
from chat_buddy.infrastructure.db.repositories import (
    ConversationRepository,
)


@pytest.fixture
def repository(
    session: Session,
) -> ConversationRepository:
    """
    Create a repository instance for testing.

    Args:
        session:
            Test database session.

    Returns:
        Repository connected to the test database.
    """

    return ConversationRepository(session)


def test_create_conversation(
    repository: ConversationRepository,
) -> None:
    """
    Verify conversation creation.
    """

    conversation = repository.create_conversation(
        title="Test Conversation",
    )

    assert conversation.id is not None
    assert conversation.title == "Test Conversation"


def test_get_conversation(
    repository: ConversationRepository,
) -> None:
    """
    Verify conversation retrieval.
    """

    created = repository.create_conversation()

    retrieved = repository.get_conversation(
        created.id,
    )

    assert retrieved is not None
    assert retrieved.id == created.id


def test_list_conversations(
    repository: ConversationRepository,
) -> None:
    """
    Verify conversation listing.
    """

    repository.create_conversation(
        title="First",
    )

    repository.create_conversation(
        title="Second",
    )

    conversations = repository.list_conversations()

    assert len(conversations) == 2


def test_add_message(
    repository: ConversationRepository,
) -> None:
    """
    Verify message creation.
    """

    conversation = repository.create_conversation()

    message = repository.add_message(
        conversation.id,
        MessageRole.USER,
        "Hello Samantha",
    )

    assert message.id is not None
    assert message.content == "Hello Samantha"


def test_get_messages(
    repository: ConversationRepository,
) -> None:
    """
    Verify message retrieval.
    """

    conversation = repository.create_conversation()

    repository.add_message(
        conversation.id,
        MessageRole.USER,
        "First",
    )

    repository.add_message(
        conversation.id,
        MessageRole.ASSISTANT,
        "Second",
    )

    messages = repository.get_messages(
        conversation.id,
    )

    assert len(messages) == 2

    assert messages[0].content == "First"
    assert messages[1].content == "Second"


def test_delete_conversation(
    repository: ConversationRepository,
) -> None:
    """
    Verify conversation deletion.
    """

    conversation = repository.create_conversation()

    deleted = repository.delete_conversation(
        conversation.id,
    )

    assert deleted is True

    assert (
        repository.get_conversation(
            conversation.id,
        )
        is None
    )


def test_delete_conversation_removes_messages(
    repository: ConversationRepository,
) -> None:
    """
    Verify cascade deletion of conversation messages.

    Deleting a conversation should automatically
    remove all associated messages via the configured
    SQLAlchemy relationship cascade.
    """

    conversation = repository.create_conversation()

    repository.add_message(
        conversation.id,
        MessageRole.USER,
        "Hello",
    )

    repository.delete_conversation(
        conversation.id,
    )

    messages = repository.get_messages(
        conversation.id,
    )

    assert messages == []
