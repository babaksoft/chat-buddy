"""Composition helpers for configured Chat providers."""

from dataclasses import dataclass

from chat_buddy.chat.domain import (
    GenerationConfiguration,
    GenerationParameter,
    LLMGateway,
    ModelDescriptor,
    ModelId,
    ProviderDescriptor,
    ProviderId,
    ProviderRegistry,
    ResponseGatewayResolver,
)
from chat_buddy.chat.infrastructure.config import settings
from chat_buddy.chat.infrastructure.llm.ollama_gateway import OllamaGateway
from chat_buddy.chat.infrastructure.llm.provider_registry import (
    StaticProviderRegistry,
    StaticResponseGatewayResolver,
)
from chat_buddy.chat.infrastructure.tokenization import MistralTokenCounter


@dataclass(slots=True, frozen=True)
class ProviderRuntime:
    """Provider-neutral services constructed from infrastructure settings."""

    registry: ProviderRegistry
    response_gateway_resolver: ResponseGatewayResolver
    legacy_gateway: LLMGateway


def build_provider_runtime() -> ProviderRuntime:
    """Build the configured Ollama provider registry and adapters.

    Returns:
        Provider-neutral runtime services for application composition.
    """

    provider_id = ProviderId(settings.OLLAMA_PROVIDER_ID)
    gateway = OllamaGateway()
    models = tuple(
        ModelDescriptor(
            provider_id=provider_id,
            id=ModelId(model_name),
            display_name=model_name,
            context_window_tokens=settings.MODEL_CONTEXT_WINDOW,
            supports_streaming=True,
            supported_generation_parameters=frozenset(GenerationParameter),
            default_generation_configuration=GenerationConfiguration(),
            token_counter=MistralTokenCounter(),
        )
        for model_name in settings.CHAT_MODELS
    )
    registry = StaticProviderRegistry(
        providers=(
            ProviderDescriptor(
                id=provider_id,
                display_name=settings.OLLAMA_PROVIDER_NAME,
            ),
        ),
        models=models,
        default_provider_id=provider_id,
        default_model_id=ModelId(settings.CHAT_MODEL),
    )
    resolver = StaticResponseGatewayResolver({provider_id: gateway})
    return ProviderRuntime(
        registry=registry,
        response_gateway_resolver=resolver,
        legacy_gateway=gateway,
    )
