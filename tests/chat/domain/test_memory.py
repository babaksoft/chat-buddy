from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from chat_buddy.chat.domain.memory import (
    ExtractionReceiptRecord,
    MemoryCandidate,
    MemoryExtractionOutcome,
    MemoryLifecycle,
    MemoryOrigin,
    MemoryOriginKind,
    MemoryRecord,
)
from chat_buddy.chat.utils.fake_data import fake_extracted_origin, fake_memory

NOW = datetime(2026, 9, 18, tzinfo=UTC)


@pytest.mark.parametrize(
    ("outcome", "attempt_count"),
    [
        (MemoryExtractionOutcome.SUCCEEDED, 1),
        (MemoryExtractionOutcome.SUCCEEDED, 3),
        (MemoryExtractionOutcome.EXHAUSTED, 3),
    ],
)
def test_extraction_receipt_accepts_terminal_bounded_outcomes(
    outcome: MemoryExtractionOutcome, attempt_count: int
) -> None:
    """Receipts represent only bounded succeeded or exhausted processing.

    Args:
        outcome:
            Terminal processing outcome.
        attempt_count:
            Number of complete processing attempts consumed.
    """

    receipt = ExtractionReceiptRecord(uuid4(), outcome, attempt_count, NOW)

    assert receipt.outcome is outcome
    assert receipt.attempt_count == attempt_count


@pytest.mark.parametrize(
    ("outcome", "attempt_count"),
    [
        (MemoryExtractionOutcome.SUCCEEDED, 0),
        (MemoryExtractionOutcome.SUCCEEDED, 4),
        (MemoryExtractionOutcome.EXHAUSTED, 2),
    ],
)
def test_extraction_receipt_rejects_invalid_attempt_counts(
    outcome: MemoryExtractionOutcome, attempt_count: int
) -> None:
    """Receipts enforce the three-attempt processing bound.

    Args:
        outcome:
            Terminal processing outcome.
        attempt_count:
            Invalid processing count.
    """

    with pytest.raises(ValueError, match="attempt"):
        ExtractionReceiptRecord(uuid4(), outcome, attempt_count, NOW)


def test_memory_candidate_requires_normalized_subject_and_content() -> None:
    """Candidates reject unnormalized or empty extractor output."""

    assert MemoryCandidate("favorite language", "Python").content == "Python"
    with pytest.raises(ValueError, match="subject"):
        MemoryCandidate("Favorite   Language", "Python")
    with pytest.raises(ValueError, match="content"):
        MemoryCandidate("editor", " VS  Code ")
    with pytest.raises(ValueError, match="non-empty"):
        MemoryCandidate("", "Python")


def test_extracted_origin_requires_all_or_no_source_identifiers() -> None:
    """Extracted provenance is complete while available and empty when cleared."""

    assert fake_extracted_origin().source_available is True
    unavailable = MemoryOrigin(
        kind=MemoryOriginKind.EXTRACTED,
        source_available=False,
    )
    assert unavailable.conversation_id is None

    with pytest.raises(ValueError, match="complete source"):
        MemoryOrigin(
            kind=MemoryOriginKind.EXTRACTED,
            conversation_id=uuid4(),
        )
    with pytest.raises(ValueError, match="clear source"):
        MemoryOrigin(
            kind=MemoryOriginKind.EXTRACTED,
            source_available=False,
            conversation_id=uuid4(),
        )


def test_correction_origin_rejects_extraction_fields_and_naive_time() -> None:
    """Correction provenance identifies only its prior revision and local time."""

    origin = MemoryOrigin(
        kind=MemoryOriginKind.USER_CORRECTION,
        superseded_revision_id=uuid4(),
        corrected_at=NOW,
    )
    assert origin.kind is MemoryOriginKind.USER_CORRECTION

    with pytest.raises(ValueError, match="cannot contain extraction"):
        MemoryOrigin(
            kind=MemoryOriginKind.USER_CORRECTION,
            conversation_id=uuid4(),
            superseded_revision_id=uuid4(),
            corrected_at=NOW,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        MemoryOrigin(
            kind=MemoryOriginKind.USER_CORRECTION,
            superseded_revision_id=uuid4(),
            corrected_at=datetime(2026, 1, 1),  # noqa: DTZ001
        )


def test_memory_allows_every_legal_lifecycle_transition() -> None:
    """Active memories may exclude or supersede and excluded memories reactivate."""

    memory = fake_memory()

    assert (
        memory.transition(MemoryLifecycle.EXCLUDED, at=NOW).lifecycle
        is MemoryLifecycle.EXCLUDED
    )
    assert (
        memory.transition(MemoryLifecycle.SUPERSEDED, at=NOW).lifecycle
        is MemoryLifecycle.SUPERSEDED
    )
    assert (
        fake_memory(MemoryLifecycle.EXCLUDED)
        .transition(MemoryLifecycle.ACTIVE, at=NOW)
        .lifecycle
        is MemoryLifecycle.ACTIVE
    )


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (MemoryLifecycle.ACTIVE, MemoryLifecycle.ACTIVE),
        (MemoryLifecycle.EXCLUDED, MemoryLifecycle.EXCLUDED),
        (MemoryLifecycle.EXCLUDED, MemoryLifecycle.SUPERSEDED),
        (MemoryLifecycle.SUPERSEDED, MemoryLifecycle.ACTIVE),
        (MemoryLifecycle.SUPERSEDED, MemoryLifecycle.EXCLUDED),
        (MemoryLifecycle.SUPERSEDED, MemoryLifecycle.SUPERSEDED),
    ],
)
def test_memory_rejects_every_illegal_lifecycle_transition(
    source: MemoryLifecycle, target: MemoryLifecycle
) -> None:
    """Memory revisions reject idempotent and forbidden state changes.

    Args:
        source:
            Initial lifecycle.
        target:
            Forbidden target lifecycle.
    """

    with pytest.raises(ValueError, match="Cannot transition"):
        fake_memory(source).transition(target, at=NOW)


def test_memory_rejects_invalid_values_and_transition_time() -> None:
    """Memory snapshots validate normalization, timestamps, and chronology."""

    values: dict[str, object] = {
        "id": uuid4(),
        "revision_id": uuid4(),
        "subject": "Favorite Language",
        "content": "Python",
        "lifecycle": MemoryLifecycle.ACTIVE,
        "origin": fake_extracted_origin(),
        "created_at": NOW,
        "updated_at": NOW,
    }
    with pytest.raises(ValueError, match="subject"):
        MemoryRecord(**values)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="last update"):
        fake_memory().transition(
            MemoryLifecycle.EXCLUDED,
            at=NOW - timedelta(seconds=1),
        )
