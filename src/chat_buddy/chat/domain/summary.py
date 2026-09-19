from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from uuid import UUID


class SummaryLifecycle(str, Enum):
    """Persisted lifecycle state of a conversation summary version."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"


@dataclass(slots=True, frozen=True)
class SummaryProvenance:
    """Conversation ownership, predecessor, and authoritative checkpoint."""

    conversation_id: UUID
    checkpoint_message_id: UUID
    predecessor_id: UUID | None = None

    def __post_init__(self) -> None:
        """Validate ownership, lineage, and checkpoint identity.

        Raises:
            ValueError:
                If provenance is incomplete or internally inconsistent.
        """

        if self.conversation_id.int == 0 or self.checkpoint_message_id.int == 0:
            raise ValueError("Summary provenance identifiers must not be nil UUIDs.")
        if self.predecessor_id is not None and self.predecessor_id.int == 0:
            raise ValueError("Summary predecessor must not be a nil UUID.")


@dataclass(slots=True, frozen=True)
class ConversationSummary:
    """Immutable conversation-owned rolling-summary version."""

    id: UUID
    conversation_id: UUID
    content: str
    created_at: datetime
    lifecycle: SummaryLifecycle
    provenance: SummaryProvenance

    def __post_init__(self) -> None:
        """Validate summary identity, content, provenance, and timestamp.

        Raises:
            ValueError:
                If the summary contains inconsistent or invalid values.
        """

        identifiers = (self.id, self.conversation_id)
        if any(identifier.int == 0 for identifier in identifiers):
            raise ValueError("Summary identifiers must not be nil UUIDs.")

        if self.provenance.predecessor_id == self.id:
            raise ValueError("A summary cannot be its own predecessor.")
        if self.provenance.conversation_id != self.conversation_id:
            raise ValueError("Summary provenance belongs to another conversation.")

        if not self.content.strip():
            raise ValueError("Summary content must be non-empty.")
        if self.content != self.content.strip():
            raise ValueError("Summary content must be trimmed.")

        if self.created_at.tzinfo is None:
            raise ValueError("Summary creation time must be timezone-aware.")

    @property
    def predecessor_id(self) -> UUID | None:
        """Return the prior version identifier, when this is a successor.

        Returns:
            Predecessor identifier, or ``None`` for an initial version.
        """

        return self.provenance.predecessor_id

    @property
    def checkpoint_message_id(self) -> UUID:
        """Return the newest assistant message incorporated by this version.

        Returns:
            Assistant-message identifier used as the ordering checkpoint.
        """

        return self.provenance.checkpoint_message_id

    def supersede(self) -> ConversationSummary:
        """Return this active summary in its terminal persisted state.

        Returns:
            A superseded copy of this summary.

        Raises:
            ValueError:
                If the summary is not active.
        """

        if self.lifecycle is not SummaryLifecycle.ACTIVE:
            raise ValueError("Only an active summary can be superseded.")

        return replace(self, lifecycle=SummaryLifecycle.SUPERSEDED)
