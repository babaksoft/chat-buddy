from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from chat_buddy.chat.domain import (
    ChatRole,
    GenerationAttemptStatus,
    GenerationConfiguration,
    InvalidGenerationAttemptTransitionError,
    ModelId,
    ProviderId,
)
from chat_buddy.chat.infrastructure.db.models import GenerationAttempt, Message
from chat_buddy.chat.infrastructure.db.repositories import (
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


def test_create_and_update_conversation_generation_defaults(
    repository: ConversationRepository,
) -> None:
    """Verify provider, model, and requested defaults round-trip.

    Args:
        repository: Repository connected to the test database.
    """

    conversation = repository.create_conversation(
        provider_id=ProviderId("ollama"),
        model_id=ModelId("mistral"),
        requested_generation_configuration=GenerationConfiguration(temperature=0.4),
    )

    assert conversation.provider_id == ProviderId("ollama")
    assert conversation.model_id == ModelId("mistral")
    assert conversation.requested_generation_configuration.temperature == 0.4

    updated = repository.update_generation_defaults(
        conversation.id,
        ProviderId("local-test"),
        ModelId("test-model"),
        GenerationConfiguration(top_p=0.8, seed=7),
    )

    assert updated is not None
    assert updated.provider_id == ProviderId("local-test")
    assert updated.model_id == ModelId("test-model")
    assert updated.requested_generation_configuration == GenerationConfiguration(
        top_p=0.8,
        seed=7,
    )


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

    conversations = repository.get_conversations()

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
        ChatRole.USER,
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
        ChatRole.USER,
        "First",
    )

    repository.add_message(
        conversation.id,
        ChatRole.ASSISTANT,
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
        ChatRole.USER,
        "Hello",
    )

    repository.delete_conversation(
        conversation.id,
    )

    messages = repository.get_messages(
        conversation.id,
    )

    assert messages == []


def test_update_conversation_title(
    repository: ConversationRepository,
) -> None:
    """
    Verify conversation title updates are persisted.
    """

    conversation = repository.create_conversation()

    updated = repository.rename_conversation(
        conversation.id,
        "Launch Planning",
    )

    assert updated is True

    retrieved = repository.get_conversation(conversation.id)

    assert retrieved is not None
    assert retrieved.title == "Launch Planning"


def test_generation_attempt_follows_completed_repository_lifecycle(
    repository: ConversationRepository,
) -> None:
    """Verify pending, streaming, checkpoint, and atomic completion persistence.

    Args:
        repository:
            Repository connected to the test database.
    """

    conversation = repository.create_conversation()
    pending = repository.start_generation_attempt(
        conversation.id,
        "Hello",
        ProviderId("ollama"),
        ModelId("mistral"),
        GenerationConfiguration(temperature=0.5, max_output_tokens=200),
    )

    assert pending.status is GenerationAttemptStatus.PENDING
    assert pending.effective_configuration.temperature == 0.5
    assert [
        message.content for message in repository.get_messages(conversation.id)
    ] == ["Hello"]

    started_at = pending.created_at + timedelta(seconds=1)
    streaming = repository.begin_generation_attempt(pending.id, at=started_at)
    checkpointed = repository.checkpoint_generation_attempt(
        streaming.id,
        "Partial response",
    )
    completed = repository.complete_generation_attempt(
        checkpointed.id,
        "Completed response",
        at=started_at + timedelta(seconds=1),
    )

    assert completed.status is GenerationAttemptStatus.COMPLETED
    assert completed.partial_content is None
    assert completed.assistant_message_id is not None
    assert [
        message.content for message in repository.get_messages(conversation.id)
    ] == [
        "Hello",
        "Completed response",
    ]
    assert repository.get_generation_attempt(completed.id) == completed


@pytest.mark.parametrize("terminal_state", ["failed", "interrupted"])
def test_generation_attempt_persists_incomplete_terminal_states(
    repository: ConversationRepository,
    terminal_state: str,
) -> None:
    """Verify failed and interrupted attempts retain partial output.

    Args:
        repository:
            Repository connected to the test database.
        terminal_state:
            Incomplete terminal transition to exercise.
    """

    conversation = repository.create_conversation()
    pending = repository.start_generation_attempt(
        conversation.id,
        "Hello",
        ProviderId("ollama"),
        ModelId("mistral"),
        GenerationConfiguration(),
    )
    started_at = pending.created_at
    repository.begin_generation_attempt(pending.id, at=started_at)

    if terminal_state == "failed":
        terminal = repository.fail_generation_attempt(
            pending.id,
            error_code="provider_unavailable",
            error_detail="Provider is unavailable.",
            partial_content="Partial",
            at=started_at + timedelta(seconds=1),
        )
    else:
        terminal = repository.interrupt_generation_attempt(
            pending.id,
            partial_content="Partial",
            at=started_at + timedelta(seconds=1),
        )

    assert terminal.status.value == terminal_state
    assert terminal.partial_content == "Partial"
    assert terminal.assistant_message_id is None
    assert [
        message.content for message in repository.get_messages(conversation.id)
    ] == ["Hello"]


def test_retry_generation_attempt_reuses_source_user_message(
    repository: ConversationRepository,
) -> None:
    """Verify retry creates provenance without duplicating ordinary history.

    Args:
        repository:
            Repository connected to the test database.
    """

    conversation = repository.create_conversation()
    original = repository.start_generation_attempt(
        conversation.id,
        "Hello",
        ProviderId("ollama"),
        ModelId("mistral"),
        GenerationConfiguration(),
    )
    repository.begin_generation_attempt(original.id, at=original.created_at)
    failed = repository.fail_generation_attempt(
        original.id,
        error_code="provider_error",
        at=original.created_at,
    )
    edited = repository.edit_unmatched_user_message(conversation.id, "Edited hello")

    retry = repository.retry_generation_attempt(
        failed.id,
        ProviderId("local-test"),
        ModelId("new-model"),
        GenerationConfiguration(temperature=0.3),
    )

    assert retry.status is GenerationAttemptStatus.PENDING
    assert retry.id != failed.id
    assert retry.source_user_message_id == failed.source_user_message_id
    assert failed.submitted_user_content == "Hello"
    assert retry.submitted_user_content == "Edited hello"
    assert edited.content == "Edited hello"
    assert retry.model_id == ModelId("new-model")
    assert [
        message.content for message in repository.get_messages(conversation.id)
    ] == ["Edited hello"]


def test_open_attempt_query_returns_one_scalar_and_excludes_terminal_attempts(
    repository: ConversationRepository,
) -> None:
    """Verify recovery exposes one open attempt rather than a collection.

    Args:
        repository:
            Repository connected to the test database.
    """

    conversation = repository.create_conversation()
    failed = repository.start_generation_attempt(
        conversation.id,
        "Failed",
        ProviderId("ollama"),
        ModelId("mistral"),
        GenerationConfiguration(),
    )
    repository.begin_generation_attempt(failed.id, at=failed.created_at)
    repository.fail_generation_attempt(
        failed.id,
        error_code="provider_error",
        at=failed.created_at,
    )
    pending = repository.start_generation_attempt(
        conversation.id,
        "Pending",
        ProviderId("ollama"),
        ModelId("mistral"),
        GenerationConfiguration(),
    )

    open_attempt = repository.get_open_generation_attempt(conversation.id)

    assert open_attempt == pending


def test_unmatched_tail_cannot_be_edited_while_attempt_is_open(
    repository: ConversationRepository,
) -> None:
    """Verify editing is limited to an unmatched tail with no open attempt.

    Args:
        repository:
            Repository connected to the test database.
    """

    conversation = repository.create_conversation()
    pending = repository.start_generation_attempt(
        conversation.id,
        "Original",
        ProviderId("ollama"),
        ModelId("mistral"),
        GenerationConfiguration(),
    )

    assert repository.get_unmatched_user_message(conversation.id) is not None
    with pytest.raises(InvalidGenerationAttemptTransitionError, match="open"):
        repository.edit_unmatched_user_message(conversation.id, "Edited")

    repository.begin_generation_attempt(pending.id, at=pending.created_at)
    repository.interrupt_generation_attempt(pending.id, at=pending.created_at)

    edited = repository.edit_unmatched_user_message(conversation.id, "Edited")

    assert edited.content == "Edited"


def test_generation_attempt_query_includes_terminal_recovery_states(
    repository: ConversationRepository,
) -> None:
    """Verify the application can retrieve attempts needed for recovery UI.

    Args:
        repository:
            Repository connected to the test database.
    """

    conversation = repository.create_conversation()
    pending = repository.start_generation_attempt(
        conversation.id,
        "Hello",
        ProviderId("ollama"),
        ModelId("mistral"),
        GenerationConfiguration(),
    )
    repository.begin_generation_attempt(pending.id, at=pending.created_at)
    failed = repository.fail_generation_attempt(
        pending.id,
        error_code="provider_error",
        at=pending.created_at,
        partial_content="Partial",
    )

    attempts = repository.get_generation_attempts(conversation.id)

    assert attempts == [failed]


def test_generation_repository_rejects_invalid_transitions(
    repository: ConversationRepository,
) -> None:
    """Verify repository operations enforce the domain lifecycle.

    Args:
        repository:
            Repository connected to the test database.
    """

    conversation = repository.create_conversation()
    pending = repository.start_generation_attempt(
        conversation.id,
        "Hello",
        ProviderId("ollama"),
        ModelId("mistral"),
        GenerationConfiguration(),
    )

    with pytest.raises(InvalidGenerationAttemptTransitionError):
        repository.checkpoint_generation_attempt(pending.id, "Too early")
    with pytest.raises(InvalidGenerationAttemptTransitionError):
        repository.complete_generation_attempt(
            pending.id,
            "Too early",
            at=pending.created_at,
        )

    repository.begin_generation_attempt(pending.id, at=pending.created_at)
    repository.interrupt_generation_attempt(pending.id, at=pending.created_at)

    with pytest.raises(InvalidGenerationAttemptTransitionError):
        repository.begin_generation_attempt(pending.id, at=pending.created_at)


def test_start_generation_attempt_rolls_back_message_and_attempt_together(
    repository: ConversationRepository,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify a failed start commit leaves neither atomic record.

    Args:
        repository:
            Repository connected to the test database.
        session:
            Database session used by the repository.
        monkeypatch:
            Pytest helper used to simulate commit failure.
    """

    conversation = repository.create_conversation()

    def fail_commit() -> None:
        """Simulate a database failure while committing the transaction."""

        raise SQLAlchemyError("simulated commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(session, "commit", fail_commit)
        with pytest.raises(SQLAlchemyError, match="simulated commit failure"):
            repository.start_generation_attempt(
                conversation.id,
                "Hello",
                ProviderId("ollama"),
                ModelId("mistral"),
                GenerationConfiguration(),
            )

    assert session.scalar(select(func.count()).select_from(Message)) == 0
    assert session.scalar(select(func.count()).select_from(GenerationAttempt)) == 0


def test_complete_generation_attempt_rolls_back_message_and_status_together(
    repository: ConversationRepository,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify a failed completion commit preserves the streaming attempt.

    Args:
        repository:
            Repository connected to the test database.
        session:
            Database session used by the repository.
        monkeypatch:
            Pytest helper used to simulate commit failure.
    """

    conversation = repository.create_conversation()
    pending = repository.start_generation_attempt(
        conversation.id,
        "Hello",
        ProviderId("ollama"),
        ModelId("mistral"),
        GenerationConfiguration(),
    )
    repository.begin_generation_attempt(pending.id, at=pending.created_at)

    def fail_commit() -> None:
        """Simulate a database failure while committing the transaction."""

        raise SQLAlchemyError("simulated commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(session, "commit", fail_commit)
        with pytest.raises(SQLAlchemyError, match="simulated commit failure"):
            repository.complete_generation_attempt(
                pending.id,
                "Response",
                at=datetime.now(UTC),
            )

    session.expire_all()
    persisted = repository.get_generation_attempt(pending.id)
    assert persisted is not None
    assert persisted.status is GenerationAttemptStatus.STREAMING
    assert [
        message.content for message in repository.get_messages(conversation.id)
    ] == ["Hello"]
