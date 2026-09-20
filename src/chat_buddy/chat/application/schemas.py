from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from chat_buddy.chat.domain import (
    GenerationConfiguration,
    GenerationParameter,
    MemoryLifecycle,
    MemoryOriginKind,
    ModelId,
    ProviderId,
)


@dataclass(slots=True, frozen=True)
class ChatRequest:
    """
    User chat request.
    """

    conversation_id: UUID | None
    message: str


@dataclass(slots=True, frozen=True)
class ChatResponse:
    """
    Assistant chat response.
    """

    conversation_id: UUID
    response: str


@dataclass(slots=True, frozen=True)
class ProviderOption:
    """Provider choice presented by the Chat application."""

    id: ProviderId
    display_name: str


@dataclass(slots=True, frozen=True)
class ModelOption:
    """Model choice and configurable capabilities presented by Chat."""

    provider_id: ProviderId
    id: ModelId
    display_name: str
    supported_generation_parameters: frozenset[GenerationParameter]


@dataclass(slots=True, frozen=True)
class GenerationSelection:
    """Selectable providers, models, and the current conversation defaults."""

    providers: tuple[ProviderOption, ...]
    models: tuple[ModelOption, ...]
    provider_id: ProviderId
    model_id: ModelId
    configuration: GenerationConfiguration


class MemoryManagementOutcome(str, Enum):
    """Outcome of a user-initiated memory-management action."""

    UPDATED = "updated"
    UNCHANGED = "unchanged"
    NOT_FOUND = "not_found"
    STALE = "stale"


@dataclass(slots=True, frozen=True)
class MemorySource:
    """Resolved source turn for an extracted Chat memory."""

    conversation_id: UUID
    conversation_title: str | None
    user_message_id: UUID
    user_message_content: str
    assistant_message_id: UUID
    assistant_message_content: str
    generation_attempt_id: UUID


@dataclass(slots=True, frozen=True)
class MemoryProvenance:
    """Persistence-neutral provenance shown by memory inspection flows."""

    kind: MemoryOriginKind
    source_available: bool
    source: MemorySource | None
    superseded_revision_id: UUID | None
    corrected_at: datetime | None


@dataclass(slots=True, frozen=True)
class ManagedMemory:
    """Application read model for one current logical Chat memory."""

    id: UUID
    revision_id: UUID
    subject: str
    content: str
    lifecycle: MemoryLifecycle
    provenance: MemoryProvenance
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class MemoryManagementResult:
    """Result of a memory correction or lifecycle action."""

    outcome: MemoryManagementOutcome
    memory: ManagedMemory | None = None
