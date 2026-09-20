"""Tests for configured Chat provider discovery and resolution."""

from collections.abc import Iterator
from unittest.mock import Mock, patch

import pytest

from chat_buddy.chat.domain import (
    ChatMessage,
    GenerationConfiguration,
    GenerationParameter,
    InvalidGenerationConfigurationError,
    ModelDescriptor,
    ModelId,
    ProviderDescriptor,
    ProviderId,
    ResponseGenerator,
    UnknownModelError,
    UnknownProviderError,
)
from chat_buddy.chat.infrastructure.config import settings
from chat_buddy.chat.infrastructure.llm import (
    StaticProviderRegistry,
    StaticResponseGatewayResolver,
    build_provider_runtime,
)


class FakeResponseGenerator:
    """Small response adapter used to exercise gateway resolution."""

    def generate(
        self,
        messages: list[ChatMessage],
        model_id: ModelId,
        configuration: GenerationConfiguration,
    ) -> str:
        """Return a fixed response.

        Args:
            messages:
                Unused conversation messages.
            model_id:
                Unused selected model.
            configuration:
                Unused effective configuration.

        Returns:
            Fixed response text.
        """

        return "response"

    def generate_stream(
        self,
        messages: list[ChatMessage],
        model_id: ModelId,
        configuration: GenerationConfiguration,
    ) -> Iterator[str]:
        """Yield a fixed response.

        Args:
            messages:
                Unused conversation messages.
            model_id:
                Unused selected model.
            configuration:
                Unused effective configuration.

        Yields:
            Fixed response text.
        """

        yield "response"


def _model(
    provider_id: ProviderId,
    model_id: str = "chat-model",
) -> ModelDescriptor:
    """Build a model descriptor for registry tests.

    Args:
        provider_id:
            Owning provider identifier.
        model_id:
            Provider-local model identifier.

    Returns:
        Test model descriptor.
    """

    return ModelDescriptor(
        provider_id=provider_id,
        id=ModelId(model_id),
        display_name="Chat model",
        context_window_tokens=8192,
        supports_streaming=True,
        supported_generation_parameters=frozenset(
            {GenerationParameter.TEMPERATURE, GenerationParameter.TOP_P}
        ),
        default_generation_configuration=GenerationConfiguration(
            temperature=0.25,
            top_p=0.9,
        ),
        token_counter=Mock(),
        default_output_token_reserve=1024,
    )


def _registry() -> tuple[StaticProviderRegistry, ModelDescriptor]:
    """Build a registry and its default model.

    Returns:
        Registry and registered default model.
    """

    provider_id = ProviderId("local")
    model = _model(provider_id)
    registry = StaticProviderRegistry(
        providers=(ProviderDescriptor(provider_id, "Local provider"),),
        models=(model,),
        default_provider_id=provider_id,
        default_model_id=model.id,
    )
    return registry, model


def test_registry_lists_and_looks_up_configured_defaults() -> None:
    """Verify configured providers, models, and the default can be discovered."""

    registry, model = _registry()

    assert registry.list_providers() == (
        ProviderDescriptor(ProviderId("local"), "Local provider"),
    )
    assert registry.list_models(ProviderId("local")) == (model,)
    assert registry.get_model(ProviderId("local"), ModelId("chat-model")) is model
    assert registry.get_default_model() is model


def test_registry_rejects_unknown_provider_and_model() -> None:
    """Verify unsupported selections fail before provider resolution."""

    registry, _ = _registry()

    with pytest.raises(UnknownProviderError, match="cloud"):
        registry.list_models(ProviderId("cloud"))
    with pytest.raises(UnknownModelError, match="missing"):
        registry.get_model(ProviderId("local"), ModelId("missing"))


def test_registry_merges_supported_configuration_with_defaults() -> None:
    """Verify requested settings override only corresponding model defaults."""

    registry, model = _registry()

    effective = registry.resolve_generation_configuration(
        model,
        GenerationConfiguration(temperature=0.7),
    )

    assert effective == GenerationConfiguration(temperature=0.7, top_p=0.9)


def test_registry_rejects_unsupported_configuration() -> None:
    """Verify unsupported settings are rejected before adapter invocation."""

    registry, model = _registry()

    with pytest.raises(
        InvalidGenerationConfigurationError,
        match="max_output_tokens",
    ):
        registry.resolve_generation_configuration(
            model,
            GenerationConfiguration(max_output_tokens=100),
        )


def test_response_gateway_resolver_uses_provider_identifier() -> None:
    """Verify response adapters resolve without leaking their concrete type."""

    provider_id = ProviderId("local")
    gateway: ResponseGenerator = FakeResponseGenerator()
    resolver = StaticResponseGatewayResolver({provider_id: gateway})

    assert resolver.resolve(provider_id) is gateway
    with pytest.raises(UnknownProviderError, match="cloud"):
        resolver.resolve(ProviderId("cloud"))


@patch("chat_buddy.chat.infrastructure.llm.ollama_gateway.Client")
def test_configured_runtime_registers_enabled_ollama_models(client_type: Mock) -> None:
    """Verify settings produce an Ollama registry and matching resolver.

    Args:
        client_type:
            Patched Ollama client constructor.
    """

    runtime = build_provider_runtime()
    provider_id = ProviderId(settings.OLLAMA_PROVIDER_ID)

    assert runtime.registry.list_providers() == (
        ProviderDescriptor(provider_id, settings.OLLAMA_PROVIDER_NAME),
    )
    assert tuple(model.id.value for model in runtime.registry.list_models()) == (
        settings.CHAT_MODELS
    )
    assert runtime.registry.get_default_model().id == ModelId(settings.CHAT_MODEL)
    assert runtime.response_gateway_resolver.resolve(provider_id) is (
        runtime.title_generator
    )
    assert runtime.summary_generator is runtime.title_generator
    assert runtime.memory_candidate_extractor is runtime.title_generator
    client_type.assert_called_once_with(host=settings.OLLAMA_ENDPOINT_URL)
