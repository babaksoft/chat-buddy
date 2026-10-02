from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.chat.domain import (
    ExtractionReceiptRecord,
    GenerationAttemptStatus,
    MemoryCandidate,
    MemoryDeletionResult,
    MemoryExtractionOutcome,
    MemoryLifecycle,
    MemoryOrigin,
    MemoryOriginKind,
    MemoryRecord,
)
from chat_buddy.chat.infrastructure.db.models import Memory
from chat_buddy.chat.infrastructure.db.repositories import (
    ConversationRepository,
    MemoryRepository,
)
from chat_buddy.chat.utils.fake_data import fake_complete_turn


def test_memory_extraction_correction_lifecycle_and_hard_delete(
    session_factory: sessionmaker[Session],
) -> None:
    """Verify memory provenance, correction, eligibility, and purge behavior.

    Args:
        session_factory:
            Isolated database session factory.
    """

    turn = fake_complete_turn(session_factory)
    repository = MemoryRepository(session_factory)
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
    session_factory: sessionmaker[Session],
) -> None:
    """Verify one terminal receipt prevents repeated candidate effects.

    Args:
        session_factory:
            Isolated database session factory.
    """

    turn = fake_complete_turn(session_factory)
    repository = MemoryRepository(session_factory)
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
    session_factory: sessionmaker[Session],
) -> None:
    """Verify automatic conflicts respect extracted, corrected, and excluded state.

    Args:
        session_factory:
            Isolated database session factory.
    """

    repository = MemoryRepository(session_factory)
    first_turn = fake_complete_turn(session_factory)
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

    second_turn = fake_complete_turn(session_factory)
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

    third_turn = fake_complete_turn(session_factory)
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
    fourth_turn = fake_complete_turn(session_factory)
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


def test_memory_rejects_stale_management_writes(
    session_factory: sessionmaker[Session],
) -> None:
    """Verify stale revision identifiers cannot partially change or delete memory.

    Args:
        session_factory:
            Isolated database session factory.
    """

    turn = fake_complete_turn(session_factory)
    repository = MemoryRepository(session_factory)
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
    deletion = repository.hard_delete(
        current.id,
        expected_revision_id=uuid4(),
    )

    assert deletion is MemoryDeletionResult.STALE
    assert repository.get_memory(current.id) == current


def test_source_unavailability_clears_extracted_references(
    session_factory: sessionmaker[Session],
) -> None:
    """Verify conversation deletion preparation retains memory without sources.

    Args:
        session_factory:
            Isolated database session factory.
    """

    turn = fake_complete_turn(session_factory)
    repository = MemoryRepository(session_factory)
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
    session_factory: sessionmaker[Session],
) -> None:
    """Verify extracted provenance must match one exact completed attempt.

    Args:
        session_factory:
            Isolated database session factory.
    """

    conversations = ConversationRepository(session_factory)
    turn = fake_complete_turn(session_factory)
    other = conversations.create_conversation()
    with session_factory() as constraint_session:
        constraint_session.add(
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
            constraint_session.commit()
