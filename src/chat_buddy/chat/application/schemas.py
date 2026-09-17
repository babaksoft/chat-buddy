from dataclasses import dataclass
from uuid import UUID

from chat_buddy.chat.domain import (
    GenerationConfiguration,
    GenerationParameter,
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
