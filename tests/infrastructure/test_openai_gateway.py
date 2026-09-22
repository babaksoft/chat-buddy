"""Tests for the OpenAI Responses infrastructure adapter."""

from types import SimpleNamespace
from unittest.mock import Mock

import openai
import pytest

from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    GenerationConfiguration,
    InvalidGenerationConfigurationError,
    ModelId,
    ProviderInvocationError,
)
from chat_buddy.chat.infrastructure.llm import OpenAIResponseGateway


def _completed_response(*contents: object) -> SimpleNamespace:
    """Build a completed SDK-shaped response.

    Args:
        *contents:
            Ordered output content parts.

    Returns:
        Minimal completed response object.
    """

    return SimpleNamespace(
        status="completed",
        output=(SimpleNamespace(content=contents),),
    )


def test_gateway_constructs_fixed_endpoint_client_with_bounded_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production construction fixes endpoint, timeout phases, and retries.

    Args:
        monkeypatch:
            Fixture used to replace the SDK client constructor.
    """

    client_type = Mock()
    monkeypatch.setattr(openai, "OpenAI", client_type)

    OpenAIResponseGateway(api_key="test-key-not-real")

    kwargs = client_type.call_args.kwargs
    assert kwargs["api_key"] == "test-key-not-real"
    assert kwargs["base_url"] == "https://api.openai.com/v1"
    assert kwargs["max_retries"] == 2
    assert vars(kwargs["timeout"]) == {
        "connect": 5.0,
        "read": 120.0,
        "write": 30.0,
        "pool": 5.0,
    }


def test_complete_response_maps_gpt_56_request_and_combines_visible_output() -> None:
    """GPT-5.6 disables reasoning and preserves text/refusal ordering."""

    client = Mock()
    client.responses.create.return_value = _completed_response(
        SimpleNamespace(type="output_text", text="answer"),
        SimpleNamespace(type="refusal", refusal=" declined"),
    )
    gateway = OpenAIResponseGateway(client=client)
    messages = [ChatMessage(ChatRole.USER, "hello")]

    result = gateway.generate(
        messages,
        ModelId("gpt-5.6-terra"),
        GenerationConfiguration(max_output_tokens=100),
    )

    assert result == "answer declined"
    client.responses.create.assert_called_once_with(
        model="gpt-5.6-terra",
        input=[{"role": "user", "content": "hello"}],
        store=False,
        reasoning={"effort": "none", "context": "current_turn"},
        max_output_tokens=100,
    )


def test_gpt_41_maps_supported_sampling_parameters_without_reasoning() -> None:
    """The pinned non-reasoning baseline receives Chat sampling settings."""

    client = Mock()
    client.responses.create.return_value = _completed_response(
        SimpleNamespace(type="output_text", text="answer")
    )
    gateway = OpenAIResponseGateway(client=client)

    gateway.generate(
        [ChatMessage(ChatRole.SYSTEM, "rules")],
        ModelId("gpt-4.1-2025-04-14"),
        GenerationConfiguration(
            temperature=0.2,
            top_p=0.8,
            max_output_tokens=50,
        ),
    )

    request = client.responses.create.call_args.kwargs
    assert request["temperature"] == 0.2
    assert request["top_p"] == 0.8
    assert request["max_output_tokens"] == 50
    assert "reasoning" not in request


def test_stream_disables_retries_and_yields_text_and_refusal_in_order() -> None:
    """A stream cannot retry and replay already emitted chunks."""

    terminal = _completed_response(SimpleNamespace(type="output_text", text="hello no"))
    stream = Mock()
    stream.__iter__ = Mock(
        return_value=iter(
            (
                SimpleNamespace(type="response.output_text.delta", delta="hello"),
                SimpleNamespace(type="response.output_text.delta", delta=""),
                SimpleNamespace(type="response.refusal.delta", delta=" no"),
                SimpleNamespace(type="response.completed", response=terminal),
            )
        )
    )
    streaming_client = Mock()
    streaming_client.responses.create.return_value = stream
    client = Mock()
    client.with_options.return_value = streaming_client
    gateway = OpenAIResponseGateway(client=client)

    chunks = gateway.generate_stream(
        [ChatMessage(ChatRole.USER, "hello")],
        ModelId("gpt-5.6-luna"),
        GenerationConfiguration(),
    )

    assert list(chunks) == ["hello", " no"]
    client.with_options.assert_called_once_with(max_retries=0)
    assert streaming_client.responses.create.call_args.kwargs["stream"] is True
    stream.close.assert_called_once_with()


@pytest.mark.parametrize(
    ("model", "configuration", "match"),
    (
        ("unknown", GenerationConfiguration(), "not enabled"),
        (
            "gpt-5.6-sol",
            GenerationConfiguration(temperature=0.5),
            "only max_output_tokens",
        ),
        (
            "gpt-4.1-2025-04-14",
            GenerationConfiguration(seed=1),
            "do not support seed",
        ),
        (
            "gpt-4.1-2025-04-14",
            GenerationConfiguration(max_output_tokens=32_769),
            "at most 32768",
        ),
    ),
)
def test_adapter_rejects_unsupported_models_and_parameters(
    model: str,
    configuration: GenerationConfiguration,
    match: str,
) -> None:
    """Adapter validation protects the boundary even without registry use.

    Args:
        model:
            Model identifier under test.
        configuration:
            Invalid effective configuration.
        match:
            Expected safe validation detail.
    """

    gateway = OpenAIResponseGateway(client=Mock())

    with pytest.raises(InvalidGenerationConfigurationError, match=match):
        gateway.generate([], ModelId(model), configuration)


@pytest.mark.parametrize("status", ("failed", "cancelled", "incomplete"))
def test_non_completed_or_empty_response_is_normalized(status: str) -> None:
    """Invalid terminal output exposes only the stable safe category.

    Args:
        status:
            Unsuccessful provider terminal status.
    """

    client = Mock()
    client.responses.create.return_value = SimpleNamespace(status=status, output=())
    gateway = OpenAIResponseGateway(client=client)

    with pytest.raises(
        ProviderInvocationError, match="^provider_invalid_response$"
    ) as raised:
        gateway.generate([], ModelId("gpt-5.6-terra"), GenerationConfiguration())

    assert raised.value.__cause__ is None


def test_sdk_failure_uses_safe_category_without_chained_payload() -> None:
    """Provider exception text and credentials cannot escape normalization."""

    client = Mock()
    client.responses.create.side_effect = openai.APIConnectionError(
        message="unsafe payload sk-test-secret",
        request=Mock(),
    )
    gateway = OpenAIResponseGateway(client=client)

    with pytest.raises(
        ProviderInvocationError, match="^provider_unavailable$"
    ) as raised:
        gateway.generate([], ModelId("gpt-5.6-terra"), GenerationConfiguration())

    assert "secret" not in str(raised.value)
    assert raised.value.__cause__ is None
