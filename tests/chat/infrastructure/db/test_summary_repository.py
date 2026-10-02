from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.chat.domain import (
    GenerationConfiguration,
    ModelId,
    ProviderId,
    SummaryLifecycle,
    SummaryProvenance,
    SummaryRecord,
)
from chat_buddy.chat.infrastructure.db.models import Summary
from chat_buddy.chat.infrastructure.db.repositories import (
    ConversationRepository,
    GenerationAttemptRepository,
    SummaryRepository,
)
from chat_buddy.chat.utils.fake_data import fake_complete_turn


def test_summary_replacement_preserves_lineage_and_uncovered_order(
    session_factory: sessionmaker[Session],
) -> None:
    """Verify atomic summary replacement and checkpoint coverage.

    Args:
        session_factory:
            Isolated database session factory.
    """

    attempts = GenerationAttemptRepository(session_factory)
    summaries = SummaryRepository(session_factory)
    first_turn = fake_complete_turn(session_factory)
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

    pending = attempts.start_generation_attempt(
        first_turn.conversation_id,
        "I prefer tea.",
        ProviderId("ollama"),
        ModelId("mistral"),
        GenerationConfiguration(),
    )
    attempts.begin_generation_attempt(pending.id, at=pending.created_at)
    completed = attempts.complete_generation_attempt(
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
    session_factory: sessionmaker[Session],
) -> None:
    """Verify summary checkpoints cannot cross conversation ownership.

    Args:
        session_factory:
            Isolated database session factory.
    """

    conversations = ConversationRepository(session_factory)
    source_turn = fake_complete_turn(session_factory)
    other = conversations.create_conversation()
    with session_factory() as constraint_session:
        constraint_session.add(
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
            constraint_session.commit()
