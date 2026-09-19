from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from uuid import UUID


def normalize_memory_text(value: str) -> str:
    """Normalize candidate text for deterministic comparisons.

    Args:
        value:
            User-derived text to normalize.

    Returns:
        Trimmed text with internal whitespace collapsed.

    Raises:
        ValueError:
            If the normalized value is empty.
    """

    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("Memory text must be non-empty.")

    return normalized


def normalize_memory_subject(value: str) -> str:
    """Normalize a memory subject used for conflict detection.

    Args:
        value:
            Candidate subject.

    Returns:
        Case-folded normalized subject.
    """

    return normalize_memory_text(value).casefold()


class MemoryLifecycle(str, Enum):
    """Persisted lifecycle state of a memory revision."""

    ACTIVE = "active"
    EXCLUDED = "excluded"
    SUPERSEDED = "superseded"


class MemoryOriginKind(str, Enum):
    """Supported provenance forms for memory revisions."""

    EXTRACTED = "extracted"
    USER_CORRECTION = "user_correction"


class MemoryDeletionResult(str, Enum):
    """Terminal outcome of a hard-delete request."""

    DELETED = "deleted"
    NOT_FOUND = "not_found"


class MemoryExtractionOutcome(str, Enum):
    """Terminal outcome of memory processing."""

    SUCCEEDED = "succeeded"
    EXHAUSTED = "exhausted"


@dataclass(slots=True, frozen=True)
class ExtractionReceiptRecord:
    """Minimal terminal receipt for one completed attempt's processing."""

    generation_attempt_id: UUID
    outcome: MemoryExtractionOutcome
    attempt_count: int
    completed_at: datetime

    def __post_init__(self) -> None:
        """Validate terminal processing identity, bound, and completion time.

        Raises:
            ValueError:
                If the receipt is malformed or violates the retry bound.
        """

        if self.generation_attempt_id.int == 0:
            raise ValueError("Extraction attempt identifier must not be nil.")

        if not 1 <= self.attempt_count <= 3:
            raise ValueError("Extraction attempt count must be between one and three.")
        if (
            self.outcome is MemoryExtractionOutcome.EXHAUSTED
            and self.attempt_count != 3
        ):
            raise ValueError("Exhausted extraction must record three attempts.")

        if self.completed_at.tzinfo is None:
            raise ValueError("Extraction completion time must be timezone-aware.")


@dataclass(slots=True, frozen=True)
class MemoryCandidate:
    """Normalized persistence-neutral memory proposed by an extractor."""

    subject: str
    content: str

    def __post_init__(self) -> None:
        """Validate that candidate values are already normalized.

        Raises:
            ValueError:
                If either value is empty or not normalized.
        """

        if self.subject != normalize_memory_subject(self.subject):
            raise ValueError("Memory candidate subject must be normalized.")
        if self.content != normalize_memory_text(self.content):
            raise ValueError("Memory candidate content must be normalized.")


@dataclass(slots=True, frozen=True)
class MemoryOrigin:
    """Exact extraction or user-correction provenance for a memory revision."""

    kind: MemoryOriginKind
    source_available: bool = True
    conversation_id: UUID | None = None
    user_message_id: UUID | None = None
    assistant_message_id: UUID | None = None
    generation_attempt_id: UUID | None = None
    superseded_revision_id: UUID | None = None
    corrected_at: datetime | None = None

    def __post_init__(self) -> None:
        """Reject inconsistent origin-field combinations.

        Raises:
            ValueError:
                If required provenance is absent or incompatible fields coexist.
        """

        extracted_values = (
            self.conversation_id,
            self.user_message_id,
            self.assistant_message_id,
            self.generation_attempt_id,
        )
        if self.kind is MemoryOriginKind.EXTRACTED:
            if self.superseded_revision_id is not None or self.corrected_at is not None:
                raise ValueError("Extracted origins cannot contain correction data.")
            if self.source_available and any(
                value is None for value in extracted_values
            ):
                raise ValueError(
                    "Available extracted origins need complete source data."
                )
            if not self.source_available and any(
                value is not None for value in extracted_values
            ):
                raise ValueError(
                    "Unavailable extracted origins must clear source data."
                )
        else:
            if not self.source_available:
                raise ValueError("Correction provenance is always locally available.")
            if any(value is not None for value in extracted_values):
                raise ValueError("Correction origins cannot contain extraction data.")
            if self.superseded_revision_id is None or self.corrected_at is None:
                raise ValueError("Correction origins need a prior revision and time.")
            if self.corrected_at.tzinfo is None:
                raise ValueError("Correction time must be timezone-aware.")

        identifiers = tuple(
            value
            for value in (*extracted_values, self.superseded_revision_id)
            if value is not None
        )
        if any(identifier.int == 0 for identifier in identifiers):
            raise ValueError("Memory provenance identifiers must not be nil UUIDs.")


@dataclass(slots=True, frozen=True)
class MemoryRecord:
    """Immutable snapshot of one revision in a logical Chat memory lineage."""

    id: UUID
    revision_id: UUID
    subject: str
    content: str
    lifecycle: MemoryLifecycle
    origin: MemoryOrigin
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        """Validate memory identity, normalized content, and timestamps.

        Raises:
            ValueError:
                If values are invalid or mutually inconsistent.
        """

        if self.id.int == 0 or self.revision_id.int == 0:
            raise ValueError("Memory identifiers must not be nil UUIDs.")

        if self.subject != normalize_memory_subject(self.subject):
            raise ValueError("Memory subject must be normalized.")
        if self.content != normalize_memory_text(self.content):
            raise ValueError("Memory content must be normalized.")

        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Memory timestamps must be timezone-aware.")
        if self.updated_at < self.created_at:
            raise ValueError("Memory cannot be updated before it is created.")

        if (
            self.origin.kind is MemoryOriginKind.USER_CORRECTION
            and self.origin.superseded_revision_id == self.revision_id
        ):
            raise ValueError("A correction cannot supersede itself.")

    def transition(self, lifecycle: MemoryLifecycle, *, at: datetime) -> MemoryRecord:
        """Apply a legal persisted lifecycle transition.

        Args:
            lifecycle:
                Requested target lifecycle.
            at:
                Time the transition occurs.

        Returns:
            Updated immutable memory snapshot.

        Raises:
            ValueError:
                If the transition or timestamp is invalid.
        """

        allowed = {
            MemoryLifecycle.ACTIVE: {
                MemoryLifecycle.EXCLUDED,
                MemoryLifecycle.SUPERSEDED,
            },
            MemoryLifecycle.EXCLUDED: {MemoryLifecycle.ACTIVE},
            MemoryLifecycle.SUPERSEDED: set(),
        }
        if lifecycle not in allowed[self.lifecycle]:
            raise ValueError(
                f"Cannot transition memory from {self.lifecycle.value} "
                f"to {lifecycle.value}."
            )

        if at.tzinfo is None:
            raise ValueError("Memory transition time must be timezone-aware.")
        if at < self.updated_at:
            raise ValueError("Memory transition cannot precede its last update.")

        return replace(self, lifecycle=lifecycle, updated_at=at)
