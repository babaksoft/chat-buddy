from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.chat.domain import (
    CompletedTurn,
    GenerationConfiguration,
    MemoryLifecycle,
    MemoryOrigin,
    MemoryOriginKind,
    MemoryRecord,
    ModelId,
    ProviderId,
    SummaryLifecycle,
    SummaryProvenance,
    SummaryRecord,
)
from chat_buddy.chat.infrastructure.db.repositories import (
    ConversationRepository,
    GenerationAttemptRepository,
)

NOW = datetime(2026, 9, 18, tzinfo=UTC)


def fake_summary(
    conversation_id: UUID,
    lifecycle: SummaryLifecycle = SummaryLifecycle.ACTIVE,
    predecessor_id: UUID | None = None,
) -> SummaryRecord:
    """Create a valid summary version for tests.

    Args:
        conversation_id:
            Owning conversation identifier.
        lifecycle:
            Lifecycle assigned to the version.
        predecessor_id:
            Optional prior summary identifier.

    Returns:
        Valid summary version.
    """

    summary_id = uuid4()
    return SummaryRecord(
        id=summary_id,
        conversation_id=conversation_id,
        content="Earlier conversation",
        created_at=NOW,
        lifecycle=lifecycle,
        provenance=SummaryProvenance(
            conversation_id=conversation_id,
            checkpoint_message_id=uuid4(),
            predecessor_id=predecessor_id,
        ),
    )


def fake_extracted_origin() -> MemoryOrigin:
    """Create complete extracted provenance for tests.

    Returns:
        Valid extracted provenance.
    """

    return MemoryOrigin(
        kind=MemoryOriginKind.EXTRACTED,
        conversation_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        generation_attempt_id=uuid4(),
    )


def fake_memory(
    lifecycle: MemoryLifecycle = MemoryLifecycle.ACTIVE,
) -> MemoryRecord:
    """Create a valid memory revision for tests.

    Args:
        lifecycle:
            Lifecycle assigned to the revision.

    Returns:
        Valid memory revision.
    """

    return MemoryRecord(
        id=uuid4(),
        revision_id=uuid4(),
        subject="favorite language",
        content="Python",
        lifecycle=lifecycle,
        origin=fake_extracted_origin(),
        created_at=NOW,
        updated_at=NOW,
    )


def fake_complete_turn(session_factory: sessionmaker[Session]) -> CompletedTurn:
    """Persist and return one exact completed turn.

    Args:
        session_factory:
            Isolated database session factory.

    Returns:
        Completed turn matching committed persistence.
    """

    conversations = ConversationRepository(session_factory)
    attempts = GenerationAttemptRepository(session_factory)
    conversation = conversations.create_conversation()
    pending = attempts.start_generation_attempt(
        conversation.id,
        "I live in Tehran.",
        ProviderId("ollama"),
        ModelId("mistral"),
        GenerationConfiguration(),
    )
    streaming = attempts.begin_generation_attempt(pending.id, at=pending.created_at)
    completed = attempts.complete_generation_attempt(
        streaming.id,
        "Thanks, I will remember that.",
        at=pending.created_at + timedelta(seconds=1),
    )
    assert completed.assistant_message_id is not None
    assert completed.finished_at is not None
    return CompletedTurn(
        conversation_id=conversation.id,
        attempt_id=completed.id,
        user_message_id=completed.source_user_message_id,
        assistant_message_id=completed.assistant_message_id,
        user_content=completed.submitted_user_content,
        assistant_content="Thanks, I will remember that.",
        completed_at=completed.finished_at,
    )
