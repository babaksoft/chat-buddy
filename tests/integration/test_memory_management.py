from datetime import timedelta

from sqlalchemy.orm import Session

from chat_buddy.chat.application.schemas import MemoryManagementOutcome
from chat_buddy.chat.application.service import MemoryManagementService
from chat_buddy.chat.domain import (
    CompletedTurn,
    ExtractionReceiptRecord,
    GenerationConfiguration,
    MemoryCandidate,
    MemoryExtractionOutcome,
    MemoryLifecycle,
    ModelId,
    ProviderId,
)
from chat_buddy.chat.infrastructure.db.repositories import (
    ConversationRepository,
    GenerationAttemptRepository,
    MemoryRepository,
)


def _complete_turn(
    conversations: ConversationRepository,
    attempts: GenerationAttemptRepository,
) -> CompletedTurn:
    """Persist and return one completed turn.

    Args:
        repository:
            Conversation repository used for persistence.

    Returns:
        Exact completed turn value.
    """

    conversation = conversations.create_conversation(title="Introductions")
    pending = attempts.start_generation_attempt(
        conversation.id,
        "I live in Tehran.",
        ProviderId("ollama"),
        ModelId("utility"),
        GenerationConfiguration(),
    )
    streaming = attempts.begin_generation_attempt(pending.id, at=pending.created_at)
    completed = attempts.complete_generation_attempt(
        streaming.id,
        "Thanks for telling me.",
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
        assistant_content="Thanks for telling me.",
        completed_at=completed.finished_at,
    )


def test_memory_management_controls_eligibility_and_purges_lineage(
    session: Session,
) -> None:
    """Verify correction, lifecycle controls, and deletion across repositories.

    Args:
        session:
            Isolated database session.
    """

    conversations = ConversationRepository(session)
    memories = MemoryRepository(session)
    turn = _complete_turn(conversations, GenerationAttemptRepository(session))
    receipt = ExtractionReceiptRecord(
        generation_attempt_id=turn.attempt_id,
        outcome=MemoryExtractionOutcome.SUCCEEDED,
        attempt_count=1,
        completed_at=turn.completed_at + timedelta(seconds=1),
    )
    memories.process_extraction(
        turn,
        (MemoryCandidate(subject="location", content="The user lives in Tehran."),),
        receipt,
    )
    extracted = memories.list_eligible_memories()[0]
    service = MemoryManagementService(
        memories,
        conversations,
        clock=lambda: receipt.completed_at + timedelta(seconds=1),
    )

    inspected = service.inspect_memory(extracted.id)
    assert inspected is not None
    assert inspected.provenance.source is not None
    assert inspected.provenance.source.conversation_title == "Introductions"
    correction = service.correct_memory(
        extracted.id,
        expected_revision_id=extracted.revision_id,
        subject="location",
        content="The user lives in Shiraz.",
    )
    assert correction.outcome is MemoryManagementOutcome.UPDATED
    assert correction.memory is not None
    assert memories.list_eligible_memories() == (memories.get_memory(extracted.id),)
    assert memories.list_eligible_memories()[0].content == "The user lives in Shiraz."
    superseded = memories.get_revision(extracted.revision_id)
    assert superseded is not None
    assert superseded.lifecycle is MemoryLifecycle.SUPERSEDED

    excluded = service.exclude_memory(
        extracted.id,
        expected_revision_id=correction.memory.revision_id,
    )
    assert excluded.outcome is MemoryManagementOutcome.UPDATED
    assert memories.list_eligible_memories() == ()
    reactivated = service.reactivate_memory(
        extracted.id,
        expected_revision_id=correction.memory.revision_id,
    )
    assert reactivated.outcome is MemoryManagementOutcome.UPDATED
    assert len(memories.list_eligible_memories()) == 1

    deleted = service.delete_memory(
        extracted.id,
        expected_revision_id=correction.memory.revision_id,
    )
    repeated = service.delete_memory(
        extracted.id,
        expected_revision_id=correction.memory.revision_id,
    )
    assert deleted.outcome is MemoryManagementOutcome.UPDATED
    assert repeated.outcome is MemoryManagementOutcome.NOT_FOUND
    assert memories.get_memory(extracted.id) is None
    assert memories.get_revision(extracted.revision_id) is None
    assert memories.get_revision(correction.memory.revision_id) is None
