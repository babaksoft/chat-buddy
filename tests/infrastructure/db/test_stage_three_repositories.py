from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chat_buddy.chat.domain import (
    ChatRole,
    CompletedTurn,
    ExtractionReceiptRecord,
    GenerationAttemptStatus,
    GenerationConfiguration,
    MemoryCandidate,
    MemoryDeletionResult,
    MemoryExtractionOutcome,
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
from chat_buddy.chat.infrastructure.db.models import (
    GenerationAttempt,
    Memory,
    Message,
    Summary,
)
from chat_buddy.chat.infrastructure.db.repositories import (
    ConversationRepository,
    MemoryRepository,
    SummaryRepository,
)


def _complete_turn(repository: ConversationRepository) -> CompletedTurn:
    """Persist and return one exact completed turn.

    Args:
        repository:
            Conversation repository under test.

    Returns:
        Completed turn matching committed persistence.
    """

    conversation = repository.create_conversation()
    pending = repository.start_generation_attempt(
        conversation.id,
        "I live in Tehran.",
        ProviderId("ollama"),
        ModelId("mistral"),
        GenerationConfiguration(),
    )
    streaming = repository.begin_generation_attempt(pending.id, at=pending.created_at)
    completed = repository.complete_generation_attempt(
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


def test_attempt_snapshot_remains_immutable_after_failed_tail_edit(
    session: Session,
) -> None:
    """Verify persisted attempt content does not follow later message edits.

    Args:
        session:
            Isolated database session.
    """

    repository = ConversationRepository(session)
    conversation = repository.create_conversation()
    pending = repository.start_generation_attempt(
        conversation.id,
        "Original",
        ProviderId("ollama"),
        ModelId("mistral"),
        GenerationConfiguration(),
    )
    repository.begin_generation_attempt(pending.id, at=pending.created_at)
    failed = repository.fail_generation_attempt(
        pending.id,
        error_code="provider_error",
        at=pending.created_at,
    )
    repository.edit_unmatched_user_message(conversation.id, "Edited")

    reloaded = repository.get_generation_attempt(failed.id)

    assert reloaded is not None
    assert reloaded.submitted_user_content == "Original"


def test_database_rejects_second_open_attempt_per_conversation(
    session: Session,
) -> None:
    """Verify the partial unique index closes the concurrent-start race.

    Args:
        session:
            Isolated database session.
    """

    repository = ConversationRepository(session)
    conversation = repository.create_conversation()
    first = repository.start_generation_attempt(
        conversation.id,
        "First",
        ProviderId("ollama"),
        ModelId("mistral"),
        GenerationConfiguration(),
    )
    second_message = Message(
        id=uuid4(),
        conversation_id=conversation.id,
        role=ChatRole.USER,
        content="Concurrent",
        created_at=first.created_at,
    )
    second = GenerationAttempt(
        id=uuid4(),
        conversation_id=conversation.id,
        source_user_message_id=second_message.id,
        submitted_user_content="Concurrent",
        provider_id="ollama",
        model_id="mistral",
        effective_configuration={},
        status=GenerationAttemptStatus.PENDING,
        created_at=first.created_at,
    )
    session.add(second_message)
    session.flush()
    session.add(second)

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_summary_replacement_preserves_lineage_and_uncovered_order(
    session: Session,
) -> None:
    """Verify atomic summary replacement and checkpoint coverage.

    Args:
        session:
            Isolated database session.
    """

    conversations = ConversationRepository(session)
    summaries = SummaryRepository(session)
    first_turn = _complete_turn(conversations)
    first = SummaryRecord(
        id=uuid4(),
        conversation_id=first_turn.conversation_id,
        content="The user lives in Tehran.",
        created_at=datetime.now(UTC),
        lifecycle=SummaryLifecycle.ACTIVE,
        provenance=SummaryProvenance(
            conversation_id=first_turn.conversation_id,
            checkpoint_message_id=first_turn.assistant_message_id,
        ),
    )

    summaries.replace_active_summary(first, expected_active_id=None)
    assert summaries.get_uncovered_completed_turns(first_turn.conversation_id) == ()

    pending = conversations.start_generation_attempt(
        first_turn.conversation_id,
        "I prefer tea.",
        ProviderId("ollama"),
        ModelId("mistral"),
        GenerationConfiguration(),
    )
    conversations.begin_generation_attempt(pending.id, at=pending.created_at)
    completed = conversations.complete_generation_attempt(
        pending.id,
        "Noted.",
        at=pending.created_at + timedelta(seconds=1),
    )
    assert completed.assistant_message_id is not None
    uncovered = summaries.get_uncovered_completed_turns(first_turn.conversation_id)
    assert [turn.attempt_id for turn in uncovered] == [completed.id]

    replacement = SummaryRecord(
        id=uuid4(),
        conversation_id=first_turn.conversation_id,
        content="The user lives in Tehran and prefers tea.",
        created_at=datetime.now(UTC),
        lifecycle=SummaryLifecycle.ACTIVE,
        provenance=SummaryProvenance(
            conversation_id=first_turn.conversation_id,
            checkpoint_message_id=completed.assistant_message_id,
            predecessor_id=first.id,
        ),
    )
    summaries.replace_active_summary(replacement, expected_active_id=first.id)

    assert summaries.get_active_summary(first_turn.conversation_id) == replacement
    persisted_first = summaries.get_summary(first.id)
    assert persisted_first is not None
    assert persisted_first.lifecycle is SummaryLifecycle.SUPERSEDED


def test_database_rejects_cross_conversation_summary_checkpoint(
    session: Session,
) -> None:
    """Verify summary checkpoints cannot cross conversation ownership.

    Args:
        session:
            Isolated database session.
    """

    conversations = ConversationRepository(session)
    source_turn = _complete_turn(conversations)
    other = conversations.create_conversation()
    session.add(
        Summary(
            id=uuid4(),
            conversation_id=other.id,
            content="Invalid",
            lifecycle=SummaryLifecycle.ACTIVE,
            checkpoint_message_id=source_turn.assistant_message_id,
            created_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_memory_extraction_correction_lifecycle_and_hard_delete(
    session: Session,
) -> None:
    """Verify memory provenance, correction, eligibility, and purge behavior.

    Args:
        session:
            Isolated database session.
    """

    turn = _complete_turn(ConversationRepository(session))
    repository = MemoryRepository(session)
    receipt = ExtractionReceiptRecord(
        generation_attempt_id=turn.attempt_id,
        outcome=MemoryExtractionOutcome.SUCCEEDED,
        attempt_count=1,
        completed_at=turn.completed_at + timedelta(seconds=1),
    )
    repository.process_extraction(
        turn,
        (MemoryCandidate(subject="location", content="The user lives in Tehran."),),
        receipt,
    )
    extracted = repository.find_current_by_subject("location")
    assert extracted is not None
    assert extracted.origin.generation_attempt_id == turn.attempt_id
    assert repository.get_extraction_receipt(turn.attempt_id) == receipt

    corrected_at = receipt.completed_at + timedelta(seconds=1)
    correction = MemoryRecord(
        id=extracted.id,
        revision_id=uuid4(),
        subject="location",
        content="The user lives in Shiraz.",
        lifecycle=MemoryLifecycle.ACTIVE,
        origin=MemoryOrigin(
            kind=MemoryOriginKind.USER_CORRECTION,
            superseded_revision_id=extracted.revision_id,
            corrected_at=corrected_at,
        ),
        created_at=corrected_at,
        updated_at=corrected_at,
    )
    repository.replace_memory(
        correction,
        expected_revision_id=extracted.revision_id,
    )
    excluded = repository.transition_memory(
        correction.id,
        expected_revision_id=correction.revision_id,
        target=MemoryLifecycle.EXCLUDED,
        at=corrected_at + timedelta(seconds=1),
    )
    assert repository.list_eligible_memories() == ()
    reactivated = repository.transition_memory(
        correction.id,
        expected_revision_id=correction.revision_id,
        target=MemoryLifecycle.ACTIVE,
        at=excluded.updated_at + timedelta(seconds=1),
    )
    assert repository.list_eligible_memories() == (reactivated,)

    assert repository.hard_delete(correction.id) is MemoryDeletionResult.DELETED
    assert repository.get_memory(correction.id) is None
    assert repository.get_revision(extracted.revision_id) is None
    assert repository.get_revision(correction.revision_id) is None


def test_receipt_is_unique_and_repeated_processing_is_idempotent(
    session: Session,
) -> None:
    """Verify one terminal receipt prevents repeated candidate effects.

    Args:
        session:
            Isolated database session.
    """

    turn = _complete_turn(ConversationRepository(session))
    repository = MemoryRepository(session)
    receipt = ExtractionReceiptRecord(
        generation_attempt_id=turn.attempt_id,
        outcome=MemoryExtractionOutcome.SUCCEEDED,
        attempt_count=1,
        completed_at=turn.completed_at + timedelta(seconds=1),
    )
    first = repository.process_extraction(turn, (), receipt)
    repeated = repository.process_extraction(
        turn,
        (MemoryCandidate(subject="ignored", content="Ignored."),),
        receipt,
    )

    assert first == repeated
    assert repository.list_memories() == ()


def test_extraction_supersedes_only_current_automatic_memory(
    session: Session,
) -> None:
    """Verify automatic conflicts respect extracted, corrected, and excluded state.

    Args:
        session:
            Isolated database session.
    """

    conversations = ConversationRepository(session)
    repository = MemoryRepository(session)
    first_turn = _complete_turn(conversations)
    first_receipt = ExtractionReceiptRecord(
        generation_attempt_id=first_turn.attempt_id,
        outcome=MemoryExtractionOutcome.SUCCEEDED,
        attempt_count=1,
        completed_at=first_turn.completed_at + timedelta(seconds=1),
    )
    repository.process_extraction(
        first_turn,
        (MemoryCandidate(subject="location", content="The user lives in Tehran."),),
        first_receipt,
    )
    first = repository.find_current_by_subject("location")
    assert first is not None

    second_turn = _complete_turn(conversations)
    second_receipt = ExtractionReceiptRecord(
        generation_attempt_id=second_turn.attempt_id,
        outcome=MemoryExtractionOutcome.SUCCEEDED,
        attempt_count=1,
        completed_at=second_turn.completed_at + timedelta(seconds=1),
    )
    repository.process_extraction(
        second_turn,
        (MemoryCandidate(subject="location", content="The user lives in Shiraz."),),
        second_receipt,
    )
    replaced = repository.find_current_by_subject("location")
    assert replaced is not None
    assert replaced.id == first.id
    assert replaced.revision_id != first.revision_id
    assert replaced.origin.generation_attempt_id == second_turn.attempt_id
    superseded = repository.get_revision(first.revision_id)
    assert superseded is not None
    assert superseded.lifecycle is MemoryLifecycle.SUPERSEDED

    corrected_at = second_receipt.completed_at + timedelta(seconds=1)
    correction = MemoryRecord(
        id=replaced.id,
        revision_id=uuid4(),
        subject="location",
        content="The user lives in Mashhad.",
        lifecycle=MemoryLifecycle.ACTIVE,
        origin=MemoryOrigin(
            kind=MemoryOriginKind.USER_CORRECTION,
            superseded_revision_id=replaced.revision_id,
            corrected_at=corrected_at,
        ),
        created_at=corrected_at,
        updated_at=corrected_at,
    )
    repository.replace_memory(
        correction,
        expected_revision_id=replaced.revision_id,
    )

    third_turn = _complete_turn(conversations)
    repository.process_extraction(
        third_turn,
        (MemoryCandidate(subject="location", content="The user lives in Isfahan."),),
        ExtractionReceiptRecord(
            generation_attempt_id=third_turn.attempt_id,
            outcome=MemoryExtractionOutcome.SUCCEEDED,
            attempt_count=1,
            completed_at=third_turn.completed_at + timedelta(seconds=1),
        ),
    )
    assert repository.find_current_by_subject("location") == correction

    excluded = repository.transition_memory(
        correction.id,
        expected_revision_id=correction.revision_id,
        target=MemoryLifecycle.EXCLUDED,
        at=corrected_at + timedelta(seconds=1),
    )
    fourth_turn = _complete_turn(conversations)
    repository.process_extraction(
        fourth_turn,
        (MemoryCandidate(subject="location", content="The user lives in Tabriz."),),
        ExtractionReceiptRecord(
            generation_attempt_id=fourth_turn.attempt_id,
            outcome=MemoryExtractionOutcome.SUCCEEDED,
            attempt_count=1,
            completed_at=fourth_turn.completed_at + timedelta(seconds=1),
        ),
    )
    assert repository.find_current_by_subject("location") == excluded


def test_memory_rejects_stale_transition_and_correction(
    session: Session,
) -> None:
    """Verify stale revision identifiers cannot partially change memory.

    Args:
        session:
            Isolated database session.
    """

    turn = _complete_turn(ConversationRepository(session))
    repository = MemoryRepository(session)
    receipt = ExtractionReceiptRecord(
        generation_attempt_id=turn.attempt_id,
        outcome=MemoryExtractionOutcome.SUCCEEDED,
        attempt_count=1,
        completed_at=turn.completed_at + timedelta(seconds=1),
    )
    repository.process_extraction(
        turn,
        (MemoryCandidate(subject="location", content="The user lives in Tehran."),),
        receipt,
    )
    current = repository.find_current_by_subject("location")
    assert current is not None
    replacement = MemoryRecord(
        id=current.id,
        revision_id=uuid4(),
        subject=current.subject,
        content="The user lives in Shiraz.",
        lifecycle=MemoryLifecycle.ACTIVE,
        origin=MemoryOrigin(
            kind=MemoryOriginKind.USER_CORRECTION,
            superseded_revision_id=current.revision_id,
            corrected_at=receipt.completed_at + timedelta(seconds=1),
        ),
        created_at=receipt.completed_at + timedelta(seconds=1),
        updated_at=receipt.completed_at + timedelta(seconds=1),
    )

    with pytest.raises(RuntimeError, match="changed"):
        repository.replace_memory(replacement, expected_revision_id=uuid4())
    with pytest.raises(RuntimeError, match="changed"):
        repository.transition_memory(
            current.id,
            expected_revision_id=uuid4(),
            target=MemoryLifecycle.EXCLUDED,
            at=receipt.completed_at + timedelta(seconds=1),
        )

    assert repository.get_memory(current.id) == current


def test_source_unavailability_clears_extracted_references(
    session: Session,
) -> None:
    """Verify conversation deletion preparation retains memory without sources.

    Args:
        session:
            Isolated database session.
    """

    turn = _complete_turn(ConversationRepository(session))
    repository = MemoryRepository(session)
    receipt = ExtractionReceiptRecord(
        generation_attempt_id=turn.attempt_id,
        outcome=MemoryExtractionOutcome.SUCCEEDED,
        attempt_count=1,
        completed_at=turn.completed_at + timedelta(seconds=1),
    )
    repository.process_extraction(
        turn,
        (MemoryCandidate(subject="location", content="The user lives in Tehran."),),
        receipt,
    )
    current = repository.find_current_by_subject("location")
    assert current is not None

    assert repository.mark_source_unavailable(turn.conversation_id) == 1
    origin = repository.get_origin(current.revision_id)

    assert origin == MemoryOrigin(
        kind=MemoryOriginKind.EXTRACTED,
        source_available=False,
    )
    assert repository.list_eligible_memories()[0].content == current.content


def test_database_rejects_invalid_memory_source_combination(
    session: Session,
) -> None:
    """Verify extracted provenance must match one exact completed attempt.

    Args:
        session:
            Isolated database session.
    """

    conversations = ConversationRepository(session)
    turn = _complete_turn(conversations)
    other = conversations.create_conversation()
    session.add(
        Memory(
            revision_id=uuid4(),
            memory_id=uuid4(),
            subject="invalid",
            content="Invalid provenance.",
            lifecycle=MemoryLifecycle.ACTIVE,
            origin_kind=MemoryOriginKind.EXTRACTED,
            source_available=True,
            source_conversation_id=other.id,
            source_user_message_id=turn.user_message_id,
            source_assistant_message_id=turn.assistant_message_id,
            source_generation_attempt_id=turn.attempt_id,
            source_generation_status=GenerationAttemptStatus.COMPLETED,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
