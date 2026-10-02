"""Characters provider contracts, resolution, and local adapter behavior."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from chat_buddy.characters.domain import (
    EffectiveGeneration,
    GenerationConfiguration,
    InvalidProviderResponseError,
    ModelDescriptor,
    ModelResolutionError,
    PromptMessage,
    ProviderInvocationError,
    ResponseGateway,
    UnsupportedGenerationError,
)
from chat_buddy.characters.infrastructure.llm import (
    ConfiguredModelRegistry,
    OllamaGateway,
    Utf8TokenCounter,
    create_model_registry,
)

PROMPT = (PromptMessage(role="user", content="Hello"),)


class FakeResponseProvider:
    """A second provider implementing only the response contract."""

    def stream(
        self, messages: tuple[PromptMessage, ...], generation: EffectiveGeneration
    ) -> Iterator[str]:
        """Yield deterministic provider text.

        Args:
            messages:
                Ordered prompt.
            generation:
                Effective model selection.

        Yields:
            Deterministic response text.
        """

        yield messages[0].content
        yield generation.model.model


def model(provider: str = "ollama", name: str = "local") -> ModelDescriptor:
    """Build configured local capabilities.

    Args:
        provider:
            Provider key.
        name:
            Model name.

    Returns:
        Immutable descriptor.
    """

    return ModelDescriptor(
        provider=provider,
        model=name,
        context_tokens=256,
        output_tokens=32,
        capabilities=frozenset(
            {"response", "summary"} if provider == "ollama" else {"response"}
        ),
        parameters=frozenset({"temperature"}),
        defaults=GenerationConfiguration(temperature=0.5),
    )


def _registry(gateway: OllamaGateway) -> ConfiguredModelRegistry:
    """Compose both providers without external calls.

    Args:
        gateway:
            Mocked local adapter.

    Returns:
        Configured model registry.
    """

    return ConfiguredModelRegistry(
        (model(), model(name="summary"), model("fake")),
        {"ollama": gateway, "fake": FakeResponseProvider()},
        {"ollama": gateway},
        {"ollama": Utf8TokenCounter(), "fake": Utf8TokenCounter()},
    )


def test_resolution_merges_defaults_and_reserves_output() -> None:
    """Effective settings preserve defaults and honor explicit output limits."""

    registry = _registry(OllamaGateway("unused", MagicMock()))
    selected = registry.resolve(
        "ollama", "local", "response", GenerationConfiguration(max_output_tokens=64)
    )
    assert selected.input_tokens == 192
    assert selected.configuration.temperature == 0.5
    assert len(registry.list_models()) == 3
    with pytest.raises(ValidationError):
        selected.input_tokens = 1
    with pytest.raises(ModelResolutionError):
        registry.resolve("unknown", "local", "response", GenerationConfiguration())
    with pytest.raises(ModelResolutionError):
        registry.token_counter("unknown")


@pytest.mark.parametrize(
    "requested",
    [
        GenerationConfiguration(seed=1),
        GenerationConfiguration(max_output_tokens=256),
        GenerationConfiguration(max_output_tokens=300),
    ],
)
def test_unsupported_requests_fail_before_provider_calls(
    requested: GenerationConfiguration,
) -> None:
    """Reject unsupported parameters and impossible reserves.

    Args:
        requested:
            Invalid request for this model.
    """

    client = MagicMock()
    registry = _registry(OllamaGateway("unused", client))
    with pytest.raises(UnsupportedGenerationError):
        registry.resolve("ollama", "local", "response", requested)
    client.chat.assert_not_called()


@pytest.mark.parametrize(
    "values",
    [
        {"temperature": float("nan")},
        {"top_p": 0},
        {"max_output_tokens": 0},
        {"seed": -1},
        {"unknown": True},
    ],
)
def test_invalid_configuration_is_rejected(values: dict[str, object]) -> None:
    """Validate requested provider-neutral values.

    Args:
        values:
            Invalid authored settings.
    """

    with pytest.raises(ValidationError):
        GenerationConfiguration.model_validate(values)


def test_response_only_provider_substitutes_the_same_contract() -> None:
    """Response-only providers do not need a summary method."""

    client = MagicMock()
    client.chat.return_value = iter(
        [{"message": {"content": "Hello"}}, {"message": {"content": "local"}}]
    )
    registry = _registry(OllamaGateway("unused", client))
    for provider in ("ollama", "fake"):
        gateway: ResponseGateway = registry.response_gateway(provider)
        selected = registry.resolve(
            provider, "local", "response", GenerationConfiguration()
        )
        assert list(gateway.stream(PROMPT, selected)) == ["Hello", "local"]
    with pytest.raises(UnsupportedGenerationError):
        registry.summary_gateway("fake")
    with pytest.raises(UnsupportedGenerationError):
        registry.resolve("fake", "local", "summary", GenerationConfiguration())


@pytest.mark.parametrize("partial", [False, True])
def test_provider_failure_is_safe_and_closes_stream(partial: bool) -> None:
    """Normalize failures on both sides of the first output chunk.

    Args:
        partial:
            Whether to yield text before failure.
    """

    closed = []

    def failing_stream() -> Iterator[dict[str, dict[str, str]]]:
        """Simulate provider interruption and record resource release.

        Yields:
            Optional initial text.
        """

        try:
            if partial:
                yield {"message": {"content": "partial"}}
            raise RuntimeError("secret provider payload")
        finally:
            closed.append(True)

    client = MagicMock()
    client.chat.return_value = failing_stream()
    registry = _registry(OllamaGateway("unused", client))
    iterator = registry.response_gateway("ollama").stream(
        PROMPT,
        registry.resolve("ollama", "local", "response", GenerationConfiguration()),
    )
    if partial:
        assert next(iterator) == "partial"
    with pytest.raises(ProviderInvocationError) as error:
        next(iterator)
    assert "secret" not in str(error.value)
    assert error.value.__suppress_context__
    assert closed == [True]


def test_consumer_close_releases_stream_and_effective_options_are_sent() -> None:
    """Cancel partial output while closing the underlying SDK iterator."""

    upstream = MagicMock()
    upstream.__iter__.return_value = iter(
        [{"message": {"content": "first"}}, {"message": {"content": "second"}}]
    )
    client = MagicMock()
    client.chat.return_value = upstream
    registry = _registry(OllamaGateway("unused", client))
    stream = registry.response_gateway("ollama").stream(
        PROMPT,
        registry.resolve("ollama", "local", "response", GenerationConfiguration()),
    )
    assert next(stream) == "first"
    stream.close()  # type: ignore[attr-defined]
    upstream.close.assert_called_once()
    assert client.chat.call_args.kwargs["options"] == {
        "num_ctx": 256,
        "num_predict": 32,
        "temperature": 0.5,
    }


@pytest.mark.parametrize("content", [" summary ", "", "  ", None, 42])
def test_summary_parsing_and_separate_model_selection(content: object) -> None:
    """Validate summary text using its independently selected model.

    Args:
        content:
            Mock provider output.
    """

    client = MagicMock()
    client.chat.return_value = {"message": {"content": content}}
    registry = _registry(OllamaGateway("unused", client))
    selected = registry.resolve(
        "ollama", "summary", "summary", GenerationConfiguration()
    )
    if content == " summary ":
        assert (
            registry.summary_gateway("ollama").summarize(PROMPT, selected) == "summary"
        )
    else:
        with pytest.raises(InvalidProviderResponseError):
            registry.summary_gateway("ollama").summarize(PROMPT, selected)
    assert client.chat.call_args.kwargs["model"] == "summary"
    assert client.chat.call_args.kwargs["stream"] is False


def test_call_failures_and_malformed_stream_are_normalized() -> None:
    """Connection failures and invalid chunks expose safe domain errors."""

    client = MagicMock()
    gateway = OllamaGateway("unused", client)
    registry = _registry(gateway)
    response = registry.resolve(
        "ollama", "local", "response", GenerationConfiguration()
    )
    summary = registry.resolve(
        "ollama", "summary", "summary", GenerationConfiguration()
    )
    client.chat.side_effect = ConnectionError("private endpoint")
    with pytest.raises(ProviderInvocationError, match="response generation failed"):
        list(gateway.stream(PROMPT, response))
    with pytest.raises(ProviderInvocationError, match="summary generation failed"):
        gateway.summarize(PROMPT, summary)
    client.chat.side_effect = None
    client.chat.return_value = iter([{}])
    with pytest.raises(InvalidProviderResponseError):
        list(gateway.stream(PROMPT, response))
    with pytest.raises(UnsupportedGenerationError):
        gateway.summarize(PROMPT, response)


def test_token_estimate_accounts_for_utf8_and_message_framing() -> None:
    """Account deterministically for non-ASCII input and multiple messages."""

    counter = Utf8TokenCounter()
    assert counter.count(()) == 8
    message = PromptMessage(role="user", content="سلام")
    assert counter.count((message,)) == 8 + 8 + 4 + len("سلام".encode())
    assert counter.count((message, message)) == 8 + 2 * (counter.count((message,)) - 8)


def test_composition_reads_characters_settings_lazily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compose independently configured models without a network call.

    Args:
        monkeypatch:
            Isolated environment settings.
    """

    monkeypatch.setenv("CHARACTERS_RESPONSE_MODEL", "response-local")
    monkeypatch.setenv("CHARACTERS_SUMMARY_MODEL", "summary-local")
    monkeypatch.setenv("CHARACTERS_OLLAMA_ENDPOINT_URL", "http://characters:11434")
    with patch(
        "chat_buddy.characters.infrastructure.llm.ollama_gateway.Client"
    ) as client:
        registry = create_model_registry()
        assert [item.model for item in registry.list_models()] == [
            "response-local",
            "summary-local",
        ]
        assert registry.resolve_default("response").model.model == "response-local"
        assert registry.resolve_default("summary").model.model == "summary-local"
        client.assert_called_once_with(host="http://characters:11434")
        client.return_value.chat.assert_not_called()


def test_invalid_model_declarations_and_bindings_fail() -> None:
    """Reject contradictory model defaults and missing capability bindings."""

    with pytest.raises(ValidationError):
        ModelDescriptor.model_validate({**model().model_dump(), "output_tokens": 256})
    with pytest.raises(ValidationError):
        ModelDescriptor.model_validate(
            {**model().model_dump(), "parameters": frozenset()}
        )
    with pytest.raises(ValueError, match="Duplicate"):
        ConfiguredModelRegistry((model(), model()), {}, {}, {})
    with pytest.raises(ValueError, match="Missing"):
        ConfiguredModelRegistry((model(),), {}, {}, {})


def test_successful_stream_closes_and_ignores_empty_chunks() -> None:
    """Close provider resources after normal stream exhaustion."""

    client = MagicMock()
    upstream = MagicMock()
    upstream.__iter__.return_value = iter(
        [
            {"message": {"content": ""}},
            {"message": {"content": "complete"}},
            {"message": {"content": ""}, "done": True},
        ]
    )
    client.chat.return_value = upstream
    registry = _registry(OllamaGateway("unused", client))
    selected = registry.resolve(
        "ollama", "local", "response", GenerationConfiguration()
    )
    assert list(registry.response_gateway("ollama").stream(PROMPT, selected)) == [
        "complete"
    ]
    upstream.close.assert_called_once()
