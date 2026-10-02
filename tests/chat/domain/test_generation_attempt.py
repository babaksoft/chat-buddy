from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from chat_buddy.chat.domain import (
    GenerationAttemptRecord,
    GenerationAttemptStatus,
    GenerationConfiguration,
    InvalidGenerationAttemptTransitionError,
    ModelId,
    ProviderId,
)


def _pending_attempt() -> GenerationAttemptRecord:
    """Build a valid pending attempt for lifecycle tests.

    Returns:
        A pending generation attempt with unique identifiers.
    """

    return GenerationAttemptRecord(
        id=uuid4(),
        conversation_id=uuid4(),
        source_user_message_id=uuid4(),
        submitted_user_content="Original question",
        provider_id=ProviderId("ollama"),
        model_id=ModelId("mistral"),
        effective_configuration=GenerationConfiguration(temperature=0.5),
        status=GenerationAttemptStatus.PENDING,
        created_at=datetime.now(UTC),
    )


def test_attempt_follows_successful_lifecycle() -> None:
    """Verify the pending-to-streaming-to-completed lifecycle."""

    pending = _pending_attempt()
    started_at = pending.created_at + timedelta(seconds=1)

    streaming = pending.start(at=started_at).checkpoint("partial")
    completed = streaming.complete(
        assistant_message_id=uuid4(),
        at=started_at + timedelta(seconds=1),
    )

    assert pending.status is GenerationAttemptStatus.PENDING
    assert streaming.status is GenerationAttemptStatus.STREAMING
    assert streaming.partial_content == "partial"
    assert completed.status is GenerationAttemptStatus.COMPLETED
    assert completed.partial_content is None
    assert completed.assistant_message_id is not None
    assert completed.effective_configuration is pending.effective_configuration


def test_attempt_follows_failed_lifecycle() -> None:
    """Verify that failure preserves safe diagnostics and partial output."""

    pending = _pending_attempt()
    streaming = pending.start(at=pending.created_at)

    failed = streaming.fail(
        error_code="provider_unavailable",
        error_detail="Provider is unavailable.",
        partial_content="partial",
        at=pending.created_at + timedelta(seconds=1),
    )

    assert failed.status is GenerationAttemptStatus.FAILED
    assert failed.partial_content == "partial"
    assert failed.error_code == "provider_unavailable"


@pytest.mark.parametrize(
    "transition",
    [
        lambda attempt: attempt.complete(
            assistant_message_id=uuid4(), at=attempt.created_at
        ),
        lambda attempt: attempt.fail(
            error_code="provider_error", at=attempt.created_at
        ),
        lambda attempt: attempt.interrupt(at=attempt.created_at),
        lambda attempt: attempt.checkpoint("partial"),
    ],
)
def test_pending_attempt_rejects_transitions_other_than_start(
    transition: object,
) -> None:
    """Verify that a pending attempt can only transition to streaming.

    Args:
        transition:
            Invalid lifecycle operation to invoke on a pending attempt.
    """

    with pytest.raises(InvalidGenerationAttemptTransitionError):
        transition(_pending_attempt())  # type: ignore[operator]


def test_terminal_attempt_rejects_further_transition() -> None:
    """Verify that a terminal attempt cannot transition again."""

    pending = _pending_attempt()
    streaming = pending.start(at=pending.created_at)
    completed = streaming.complete(assistant_message_id=uuid4(), at=pending.created_at)

    with pytest.raises(InvalidGenerationAttemptTransitionError):
        completed.interrupt(at=pending.created_at)


def test_attempt_requires_timezone_aware_timestamps() -> None:
    """Verify that generation attempt timestamps include timezone data."""

    with pytest.raises(ValueError, match="timezone-aware"):
        GenerationAttemptRecord(
            id=uuid4(),
            conversation_id=uuid4(),
            source_user_message_id=uuid4(),
            submitted_user_content="Question",
            provider_id=ProviderId("ollama"),
            model_id=ModelId("mistral"),
            effective_configuration=GenerationConfiguration(),
            status=GenerationAttemptStatus.PENDING,
            created_at=datetime(2026, 1, 1),  # noqa: DTZ001 - intentionally naive
        )


def test_attempt_is_immutable() -> None:
    """Verify that generation attempt fields cannot be reassigned."""

    attempt = _pending_attempt()

    with pytest.raises(FrozenInstanceError):
        attempt.status = GenerationAttemptStatus.STREAMING  # type: ignore[misc]


def test_attempt_preserves_immutable_submitted_user_content() -> None:
    """Verify each attempt owns a validated immutable input snapshot."""

    attempt = _pending_attempt()

    assert attempt.submitted_user_content == "Original question"
    with pytest.raises(FrozenInstanceError):
        attempt.submitted_user_content = "Edited"  # type: ignore[misc]


def test_attempt_rejects_blank_submitted_user_content() -> None:
    """Verify an attempt cannot omit its submitted-content provenance."""

    attempt = _pending_attempt()
    with pytest.raises(ValueError, match="Submitted user content"):
        replace(attempt, submitted_user_content="  ")


@pytest.mark.parametrize(
    ("status", "is_open", "is_retryable"),
    [
        (GenerationAttemptStatus.PENDING, True, False),
        (GenerationAttemptStatus.STREAMING, True, False),
        (GenerationAttemptStatus.COMPLETED, False, False),
        (GenerationAttemptStatus.FAILED, False, True),
        (GenerationAttemptStatus.INTERRUPTED, False, True),
    ],
)
def test_attempt_status_defines_open_and_retryable_concepts(
    status: GenerationAttemptStatus, is_open: bool, is_retryable: bool
) -> None:
    """Verify linear-turn status categories are singular and explicit.

    Args:
        status:
            Lifecycle state to classify.
        is_open:
            Expected open-state classification.
        is_retryable:
            Expected retryable-state classification.
    """

    assert status.is_open is is_open
    assert status.is_retryable is is_retryable
