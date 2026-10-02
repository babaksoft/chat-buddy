from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest

from chat_buddy.chat.application.service import (
    MemoryExtractionService,
)
from chat_buddy.chat.domain import (
    CompletedTurn,
    ExtractionReceiptRecord,
    MemoryCandidate,
    MemoryExtractionOutcome,
)

NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)


def _turn() -> CompletedTurn:
    """Create exact committed source data for extraction tests.

    Returns:
        Valid memory-extraction source.
    """

    return CompletedTurn(
        conversation_id=uuid4(),
        attempt_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        user_content="I live in Tehran.",
        assistant_content="Thanks, I will remember that.",
        completed_at=NOW,
    )


def _service(repository: Mock, extractor: Mock) -> MemoryExtractionService:
    """Build the service with a deterministic clock.

    Args:
        repository:
            Memory repository double.
        extractor:
            Candidate extractor double.

    Returns:
        Configured extraction service.
    """

    return MemoryExtractionService(
        repository=repository,
        extractor=extractor,
        clock=lambda: NOW + timedelta(seconds=1),
    )


def test_memory_source_persists_candidates_and_receipt_atomically() -> None:
    """Verify source candidates and success metadata share one operation."""

    turn = _turn()
    repository = Mock()
    repository.get_extraction_receipt.return_value = None
    extractor = Mock()
    candidates = (
        MemoryCandidate(subject="location", content="The user lives in Tehran."),
    )
    extractor.extract_candidates.return_value = candidates
    repository.process_extraction.side_effect = lambda _, __, receipt: receipt

    receipt = _service(repository, extractor).process(turn)

    extractor.extract_candidates.assert_called_once_with(turn)
    repository.process_extraction.assert_called_once_with(turn, candidates, receipt)
    assert receipt.outcome is MemoryExtractionOutcome.SUCCEEDED
    assert receipt.attempt_count == 1


def test_empty_candidate_set_is_a_success() -> None:
    """Verify a valid empty provider result reaches a terminal success."""

    turn = _turn()
    repository = Mock()
    repository.get_extraction_receipt.return_value = None
    repository.process_extraction.side_effect = lambda _, __, receipt: receipt
    extractor = Mock()
    extractor.extract_candidates.return_value = ()

    receipt = _service(repository, extractor).process(turn)

    assert receipt.outcome is MemoryExtractionOutcome.SUCCEEDED
    repository.process_extraction.assert_called_once_with(turn, (), receipt)


def test_identical_candidates_are_deduplicated_before_persistence() -> None:
    """Verify duplicate provider output cannot create duplicate effects."""

    turn = _turn()
    repository = Mock()
    repository.get_extraction_receipt.return_value = None
    repository.process_extraction.side_effect = lambda _, __, receipt: receipt
    extractor = Mock()
    candidate = MemoryCandidate(
        subject="favorite language",
        content="The user prefers Python.",
    )
    extractor.extract_candidates.return_value = (candidate, candidate)

    _service(repository, extractor).process(turn)

    assert repository.process_extraction.call_args.args[1] == (candidate,)


def test_conflicting_duplicate_subject_exhausts_without_candidate_writes() -> None:
    """Verify ambiguous provider candidates never partially reach persistence."""

    turn = _turn()
    repository = Mock()
    repository.get_extraction_receipt.return_value = None
    repository.process_extraction.side_effect = lambda _, __, receipt: receipt
    extractor = Mock()
    extractor.extract_candidates.return_value = (
        MemoryCandidate(subject="location", content="The user lives in Tehran."),
        MemoryCandidate(subject="location", content="The user lives in Shiraz."),
    )

    receipt = _service(repository, extractor).process(turn)

    assert receipt.outcome is MemoryExtractionOutcome.EXHAUSTED
    assert extractor.extract_candidates.call_count == 3
    repository.process_extraction.assert_called_once_with(turn, (), receipt)


@pytest.mark.parametrize("failure_source", ["utility", "persistence"])
def test_processing_failure_retries_at_most_three_times(
    failure_source: str,
) -> None:
    """Verify utility and transaction failures terminate as exhausted.

    Args:
        failure_source:
            Processing stage configured to fail.
    """

    turn = _turn()
    repository = Mock()
    repository.get_extraction_receipt.return_value = None
    extractor = Mock()
    extractor.extract_candidates.return_value = (
        MemoryCandidate(subject="location", content="The user lives in Tehran."),
    )
    if failure_source == "utility":
        extractor.extract_candidates.side_effect = ValueError("invalid provider data")

    exhausted = ExtractionReceiptRecord(
        generation_attempt_id=turn.attempt_id,
        outcome=MemoryExtractionOutcome.EXHAUSTED,
        attempt_count=3,
        completed_at=NOW + timedelta(seconds=1),
    )

    def process(
        processed_turn: CompletedTurn,
        candidates: tuple[MemoryCandidate, ...],
        receipt: ExtractionReceiptRecord,
    ) -> ExtractionReceiptRecord:
        """Fail success writes and accept only the exhausted receipt.

        Args:
            processed_turn:
                Exact source turn.
            candidates:
                Candidate transaction contents.
            receipt:
                Proposed terminal receipt.

        Returns:
            Exhausted terminal receipt.
        """

        if receipt.outcome is MemoryExtractionOutcome.SUCCEEDED:
            raise RuntimeError("transaction failed")
        assert processed_turn == turn
        assert candidates == ()
        return receipt

    if failure_source == "persistence":
        repository.process_extraction.side_effect = process
    else:
        repository.process_extraction.side_effect = process

    receipt = _service(repository, extractor).process(turn)

    assert receipt == exhausted
    assert extractor.extract_candidates.call_count == 3
    if failure_source == "utility":
        assert repository.process_extraction.call_count == 1
    else:
        assert repository.process_extraction.call_count == 4


def test_second_processing_attempt_can_succeed() -> None:
    """Verify transient validation failure records the consumed attempt count."""

    turn = _turn()
    repository = Mock()
    repository.get_extraction_receipt.return_value = None
    repository.process_extraction.side_effect = lambda _, __, receipt: receipt
    extractor = Mock()
    extractor.extract_candidates.side_effect = [
        ValueError("invalid JSON"),
        (MemoryCandidate(subject="location", content="The user lives in Tehran."),),
    ]

    receipt = _service(repository, extractor).process(turn)

    assert receipt.outcome is MemoryExtractionOutcome.SUCCEEDED
    assert receipt.attempt_count == 2
    assert extractor.extract_candidates.call_count == 2


def test_existing_terminal_receipt_skips_provider_and_candidate_work() -> None:
    """Verify either terminal outcome makes a repeated callback a no-op."""

    turn = _turn()
    existing = ExtractionReceiptRecord(
        generation_attempt_id=turn.attempt_id,
        outcome=MemoryExtractionOutcome.EXHAUSTED,
        attempt_count=3,
        completed_at=NOW + timedelta(seconds=1),
    )
    repository = Mock()
    repository.get_extraction_receipt.return_value = existing
    extractor = Mock()

    result = _service(repository, extractor).process(turn)

    assert result == existing
    extractor.extract_candidates.assert_not_called()
    repository.process_extraction.assert_not_called()
