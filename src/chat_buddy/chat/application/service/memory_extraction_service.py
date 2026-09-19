"""Bounded post-completion memory extraction orchestration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from chat_buddy.chat.domain import (
    ChatMemoryRepository,
    CompletedTurn,
    ExtractionReceiptRecord,
    MemoryCandidate,
    MemoryCandidateExtractor,
    MemoryExtractionOutcome,
    normalize_memory_subject,
    normalize_memory_text,
)

logger = logging.getLogger(__name__)

_MAX_PROCESSING_ATTEMPTS = 3


class MemoryExtractionService:
    """Extract memory from one committed turn with bounded best-effort retries."""

    def __init__(
        self,
        repository: ChatMemoryRepository,
        extractor: MemoryCandidateExtractor,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize bounded memory extraction.

        Args:
            repository:
                Provenance-aware Chat memory persistence.
            extractor:
                Utility-provider adapter for exact committed exchanges.
            clock:
                Optional timezone-aware clock used by tests.
        """

        self._repository = repository
        self._extractor = extractor
        self._clock = clock or (lambda: datetime.now(UTC))

    def process(self, turn: CompletedTurn) -> ExtractionReceiptRecord:
        """Process a memory source to one terminal durable outcome.

        Args:
            turn:
                Exact committed user/assistant pair and its provenance.

        Returns:
            Existing, succeeded, or exhausted terminal receipt.

        Raises:
            Exception:
                If the terminal exhausted receipt itself cannot be persisted.
        """

        existing = self._repository.get_extraction_receipt(turn.attempt_id)
        if existing is not None:
            return existing

        for attempt_count in range(1, _MAX_PROCESSING_ATTEMPTS + 1):
            try:
                extracted = self._extractor.extract_candidates(turn)
                candidates = self._normalize_candidates(extracted)
                receipt = ExtractionReceiptRecord(
                    generation_attempt_id=turn.attempt_id,
                    outcome=MemoryExtractionOutcome.SUCCEEDED,
                    attempt_count=attempt_count,
                    completed_at=self._completion_time(turn),
                )
                persisted = self._repository.process_extraction(
                    turn,
                    candidates,
                    receipt,
                )
                logger.info(
                    "Completed memory extraction for attempt %s: "
                    "processing_attempts=%d candidates=%d",
                    turn.attempt_id,
                    attempt_count,
                    len(candidates),
                )
                return persisted
            except Exception:
                logger.warning(
                    "Memory extraction processing attempt %d/%d failed for "
                    "generation attempt %s.",
                    attempt_count,
                    _MAX_PROCESSING_ATTEMPTS,
                    turn.attempt_id,
                    exc_info=True,
                )

        exhausted = ExtractionReceiptRecord(
            generation_attempt_id=turn.attempt_id,
            outcome=MemoryExtractionOutcome.EXHAUSTED,
            attempt_count=_MAX_PROCESSING_ATTEMPTS,
            completed_at=self._completion_time(turn),
        )
        persisted = self._repository.process_extraction(turn, (), exhausted)
        logger.error(
            "Memory extraction exhausted for generation attempt %s after %d attempts.",
            turn.attempt_id,
            _MAX_PROCESSING_ATTEMPTS,
        )
        return persisted

    def _completion_time(self, turn: CompletedTurn) -> datetime:
        """Return a valid processing completion timestamp.

        Args:
            turn:
                Completed source turn.

        Returns:
            Timezone-aware time no earlier than turn completion.

        Raises:
            ValueError:
                If the configured clock returns a naive timestamp.
        """

        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("Memory extraction clock must be timezone-aware.")
        return max(now, turn.completed_at)

    @staticmethod
    def _normalize_candidates(
        candidates: tuple[MemoryCandidate, ...],
    ) -> tuple[MemoryCandidate, ...]:
        """Normalize, validate, and deterministically deduplicate candidates.

        Identical duplicates collapse to one candidate. Conflicting content for
        one normalized subject rejects the entire provider result so it can be
        retried without applying ambiguous effects.

        Args:
            candidates:
                Candidate set returned by the utility-provider adapter.

        Returns:
            Unique normalized candidates in provider order.

        Raises:
            ValueError:
                If one subject has conflicting candidate content.
        """

        normalized: list[MemoryCandidate] = []
        content_by_subject: dict[str, str] = {}
        for candidate in candidates:
            subject = normalize_memory_subject(candidate.subject)
            content = normalize_memory_text(candidate.content)
            prior_content = content_by_subject.get(subject)
            if prior_content is not None:
                if prior_content != content:
                    raise ValueError(
                        "Memory extraction returned conflicting content for one "
                        "subject."
                    )
                continue
            content_by_subject[subject] = content
            normalized.append(MemoryCandidate(subject=subject, content=content))
        return tuple(normalized)
