"""Privacy-safe structured diagnostic contracts for Characters workflows."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from chat_buddy.characters.domain.continuity import ContinuityMode


class CharactersDiagnosticName(StrEnum):
    """Stable low-cardinality Characters diagnostic names."""

    TIMELINE_START = "timeline_start"
    TIMELINE_DAY_RESERVATION = "timeline_day_reservation"
    TIMELINE_CLOSURE = "timeline_closure"
    TIMELINE_HISTORICAL_REJECTION = "timeline_historical_rejection"
    RESPONSE_STYLE_REVISION = "response_style_revision"
    RESPONSE_CONTEXT_ASSEMBLY = "response_context_assembly"
    MEMORY_EXTRACTION_TERMINAL = "memory_extraction_terminal"
    EVOLUTION_TERMINAL = "evolution_terminal"
    ATTEMPT_RECOVERY = "attempt_recovery"


class CharactersDiagnostic(BaseModel):
    """Allowlisted diagnostic facts that exclude authored and generated content.

    Attributes:
        name:
            Stable event name.
        continuity_id:
            Owning continuity identifier when known.
        conversation_id:
            Exact conversation identifier when relevant.
        entry_id:
            Exact scene or Timeline day identifier when relevant.
        attempt_id:
            Exact generation attempt identifier when relevant.
        mode:
            Owning continuity mode when known.
        local_date:
            Represented Timeline local date when relevant.
        boundary_timezone:
            Stored IANA boundary timezone when relevant.
        policy:
            Stable policy or selector name when relevant.
        version:
            Stable policy or renderer version when relevant.
        terminal_reason:
            Bounded application outcome or rejection reason.
        latency_seconds:
            Monotonic operation duration when measured.
        recovered_attempt_count:
            Number of scoped interrupted attempts recovered.
        included_turn_count:
            Number of complete turns selected for response context.
        omitted_turn_count:
            Number of complete turns omitted from response context.
        token_count:
            Estimated selected response-context tokens.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: CharactersDiagnosticName = Field(description="Stable event name.")
    continuity_id: UUID | None = Field(
        default=None, description="Owning continuity identifier when known."
    )
    conversation_id: UUID | None = Field(
        default=None, description="Exact conversation identifier when relevant."
    )
    entry_id: UUID | None = Field(
        default=None, description="Exact Entry identifier when relevant."
    )
    attempt_id: UUID | None = Field(
        default=None, description="Exact generation attempt identifier when relevant."
    )
    mode: ContinuityMode | None = Field(
        default=None, description="Owning continuity mode when known."
    )
    local_date: date | None = Field(
        default=None, description="Represented Timeline local date when relevant."
    )
    boundary_timezone: str | None = Field(
        default=None,
        max_length=64,
        description="Stored IANA boundary timezone when relevant.",
    )
    policy: str | None = Field(
        default=None, max_length=128, description="Stable policy or selector name."
    )
    version: str | None = Field(
        default=None, max_length=32, description="Stable policy or renderer version."
    )
    terminal_reason: str = Field(
        min_length=1,
        max_length=64,
        description="Bounded application outcome or rejection reason.",
    )
    latency_seconds: float | None = Field(
        default=None,
        ge=0,
        description="Monotonic operation duration when measured.",
    )
    recovered_attempt_count: int | None = Field(
        default=None,
        ge=0,
        description="Number of scoped interrupted attempts recovered.",
    )
    included_turn_count: int | None = Field(
        default=None,
        ge=0,
        description="Number of response-context turns selected.",
    )
    omitted_turn_count: int | None = Field(
        default=None,
        ge=0,
        description="Number of response-context turns omitted.",
    )
    token_count: int | None = Field(
        default=None,
        ge=0,
        description="Estimated selected response-context tokens.",
    )


class CharactersDiagnosticObserver(Protocol):
    """Receive allowlisted Characters diagnostics without business authority."""

    def emit(self, diagnostic: CharactersDiagnostic) -> None:
        """Record one privacy-safe diagnostic.

        Args:
            diagnostic:
                Validated allowlisted event.
        """

        ...
