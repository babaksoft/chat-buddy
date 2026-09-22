from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from chat_buddy.chat.application.service import (
    MemoryExtractionService,
)
from chat_buddy.chat.domain import (
    CompletedTurn,
    GenerationConfiguration,
    MemoryCandidate,
    MemoryExtractionOutcome,
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
    """Persist and return one exact completed source turn.

    Args:
        repository:
            Conversation repository used for persistence.

    Returns:
        Exact committed turn.
    """

    conversation = conversations.create_conversation()
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
        at=streaming.started_at or streaming.created_at,
    )
    assert completed.assistant_message_id is not None
    assert completed.finished_at is not None
    return CompletedTurn(
        conversation_id=completed.conversation_id,
        attempt_id=completed.id,
        user_message_id=completed.source_user_message_id,
        assistant_message_id=completed.assistant_message_id,
        user_content=completed.submitted_user_content,
        assistant_content="Thanks for telling me.",
        completed_at=completed.finished_at,
    )


def test_memory_extraction_is_durable_chat_wide_and_idempotent(
    session: Session,
) -> None:
    """Verify service/repository extraction persists provenance once.

    Args:
        session:
            Isolated database session.
    """

    turn = _complete_turn(
        ConversationRepository(session), GenerationAttemptRepository(session)
    )
    memory_repository = MemoryRepository(session)
    extractor = Mock()
    extractor.extract_candidates.return_value = (
        MemoryCandidate(subject="location", content="The user lives in Tehran."),
    )
    service = MemoryExtractionService(
        repository=memory_repository,
        extractor=extractor,
        clock=lambda: datetime.now(UTC),
    )

    first = service.process(turn)
    repeated = service.process(turn)
    other_conversation = ConversationRepository(session).create_conversation()
    eligible_for_other_conversation = memory_repository.list_eligible_memories()

    assert other_conversation.id != turn.conversation_id
    assert first.outcome is MemoryExtractionOutcome.SUCCEEDED
    assert repeated == first
    extractor.extract_candidates.assert_called_once_with(turn)
    assert len(eligible_for_other_conversation) == 1
    memory = eligible_for_other_conversation[0]
    assert memory.origin.conversation_id == turn.conversation_id
    assert memory.origin.user_message_id == turn.user_message_id
    assert memory.origin.assistant_message_id == turn.assistant_message_id
    assert memory.origin.generation_attempt_id == turn.attempt_id


def test_failed_candidate_transactions_roll_back_before_exhaustion(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify failed candidate writes leave only an exhausted receipt.

    Args:
        session:
            Isolated database session.
        monkeypatch:
            Fixture used to simulate transaction failures.
    """

    turn = _complete_turn(
        ConversationRepository(session), GenerationAttemptRepository(session)
    )
    memory_repository = MemoryRepository(session)
    extractor = Mock()
    extractor.extract_candidates.return_value = (
        MemoryCandidate(subject="location", content="The user lives in Tehran."),
    )
    original_commit = session.commit
    commit_count = 0

    def fail_candidate_commits() -> None:
        """Fail three candidate commits, then allow the exhausted receipt.

        Raises:
            SQLAlchemyError:
                For each of the three candidate transactions.
        """

        nonlocal commit_count
        commit_count += 1
        if commit_count <= 3:
            raise SQLAlchemyError("simulated transaction failure")
        original_commit()

    monkeypatch.setattr(session, "commit", Mock(side_effect=fail_candidate_commits))
    service = MemoryExtractionService(
        repository=memory_repository,
        extractor=extractor,
        clock=lambda: datetime.now(UTC),
    )

    receipt = service.process(turn)

    assert receipt.outcome is MemoryExtractionOutcome.EXHAUSTED
    assert receipt.attempt_count == 3
    assert memory_repository.list_memories() == ()
    assert memory_repository.get_extraction_receipt(turn.attempt_id) == receipt
