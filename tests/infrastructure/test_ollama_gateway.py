from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from ollama import RequestError, ResponseError

from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    CompletedTurn,
    GenerationConfiguration,
    MemoryCandidate,
    ModelId,
    ProviderInvocationError,
    ResponseGenerator,
)
from chat_buddy.chat.infrastructure.config import settings
from chat_buddy.chat.infrastructure.llm import OllamaGateway


def _memory_source() -> CompletedTurn:
    """Create committed source data for utility-adapter tests.

    Returns:
        Exact test turn.
    """

    return CompletedTurn(
        conversation_id=uuid4(),
        attempt_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        user_content="  I live in Tehran.  ",
        assistant_content="Thanks for telling me.",
        completed_at=datetime.now(UTC),
    )


@patch("chat_buddy.chat.infrastructure.llm.ollama_gateway.Client")
def test_uses_chat_settings_by_default(client_type: Mock) -> None:
    gateway = OllamaGateway()

    client_type.assert_called_once_with(host=settings.OLLAMA_ENDPOINT_URL)
    assert gateway._chat_model == settings.CHAT_MODEL
    assert gateway._utility_model == settings.UTILITY_MODEL


@patch("chat_buddy.chat.infrastructure.llm.ollama_gateway.Client")
def test_generate_sends_domain_messages_to_ollama(client_type: Mock) -> None:
    client = client_type.return_value
    client.chat.return_value = {
        "message": {"content": "Hello"},
        "prompt_eval_count": 4,
        "eval_count": 2,
    }
    gateway = OllamaGateway(model_name="chat-model", host="http://ollama.test")

    response = gateway.generate([ChatMessage(role=ChatRole.USER, content="Hi")])

    assert response == "Hello"
    client_type.assert_called_once_with(host="http://ollama.test")
    client.chat.assert_called_once_with(
        model="chat-model",
        messages=[{"role": "user", "content": "Hi"}],
    )


@patch("chat_buddy.chat.infrastructure.llm.ollama_gateway.Client")
def test_generate_uses_selected_model_and_translates_configuration(
    client_type: Mock,
) -> None:
    """Verify the response interface maps neutral settings to Ollama options.

    Args:
        client_type:
            Mocked Ollama client constructor.
    """

    client = client_type.return_value
    client.chat.return_value = {
        "message": {"content": "Hello"},
        "prompt_eval_count": 4,
        "eval_count": 2,
    }
    gateway: ResponseGenerator = OllamaGateway(host="http://ollama.test")

    response = gateway.generate(
        [ChatMessage(role=ChatRole.USER, content="Hi")],
        ModelId("selected-model"),
        GenerationConfiguration(
            temperature=0.4,
            top_p=0.8,
            max_output_tokens=200,
            seed=7,
        ),
    )

    assert response == "Hello"
    client.chat.assert_called_once_with(
        model="selected-model",
        messages=[{"role": "user", "content": "Hi"}],
        options={
            "temperature": 0.4,
            "top_p": 0.8,
            "num_predict": 200,
            "seed": 7,
        },
    )


@patch("chat_buddy.chat.infrastructure.llm.ollama_gateway.Client")
def test_generate_stream_preserves_chunked_response(client_type: Mock) -> None:
    """Verify the response interface yields Ollama chunks in order.

    Args:
        client_type:
            Mocked Ollama client constructor.
    """

    client = client_type.return_value
    client.chat.return_value = iter(
        [
            {"message": {"content": "Hel"}},
            {"message": {"content": ""}},
            {"message": {"content": "lo"}},
        ]
    )
    gateway: ResponseGenerator = OllamaGateway(host="http://ollama.test")

    chunks = list(
        gateway.generate_stream(
            [ChatMessage(role=ChatRole.USER, content="Hi")],
            ModelId("selected-model"),
            GenerationConfiguration(temperature=0.4),
        )
    )

    assert chunks == ["Hel", "lo"]
    client.chat.assert_called_once_with(
        model="selected-model",
        messages=[{"role": "user", "content": "Hi"}],
        stream=True,
        options={"temperature": 0.4},
    )


@pytest.mark.parametrize(
    "provider_error",
    [RequestError("connection details"), ResponseError("server details", 500)],
)
@patch("chat_buddy.chat.infrastructure.llm.ollama_gateway.Client")
def test_generate_normalizes_provider_failures(
    client_type: Mock,
    provider_error: RequestError | ResponseError,
) -> None:
    """Verify Ollama exceptions do not escape the infrastructure boundary.

    Args:
        client_type:
            Mocked Ollama client constructor.
        provider_error:
            Provider-specific failure raised by the client.
    """

    client_type.return_value.chat.side_effect = provider_error
    gateway = OllamaGateway(host="http://ollama.test")

    with pytest.raises(ProviderInvocationError, match="Provider 'ollama'") as raised:
        gateway.generate(
            [ChatMessage(role=ChatRole.USER, content="Hi")],
            ModelId("selected-model"),
            GenerationConfiguration(),
        )

    assert raised.value.__cause__ is provider_error
    assert "details" not in str(raised.value)


@patch("chat_buddy.chat.infrastructure.llm.ollama_gateway.Client")
def test_generate_stream_normalizes_iteration_failure(client_type: Mock) -> None:
    """Verify provider failures during stream consumption are normalized.

    Args:
        client_type:
            Mocked Ollama client constructor.
    """

    provider_error = ResponseError("stream details", 500)

    def failing_stream() -> Iterator[dict[str, dict[str, str]]]:
        """Yield one chunk and then simulate a provider stream failure.

        Yields:
            One response chunk before failure.
        """

        yield {"message": {"content": "partial"}}
        raise provider_error

    client_type.return_value.chat.return_value = failing_stream()
    gateway = OllamaGateway(host="http://ollama.test")
    stream = gateway.generate_stream(
        [ChatMessage(role=ChatRole.USER, content="Hi")],
        ModelId("selected-model"),
        GenerationConfiguration(),
    )

    assert next(stream) == "partial"
    with pytest.raises(ProviderInvocationError) as raised:
        next(stream)
    assert raised.value.__cause__ is provider_error


@patch("chat_buddy.chat.infrastructure.llm.ollama_gateway.Client")
def test_extract_candidates_uses_exact_pair_and_normalizes_values(
    client_type: Mock,
) -> None:
    """Verify the utility adapter includes both messages and normalizes output.

    Args:
        client_type:
            Mocked Ollama client constructor.
    """

    client_type.return_value.chat.return_value = {
        "message": {
            "content": '[{"key": " Home City ", "value": " Lives  in Tehran. "}]'
        },
        "prompt_eval_count": 4,
        "eval_count": 2,
    }
    gateway = OllamaGateway(host="http://ollama.test")
    turn = _memory_source()

    candidates = gateway.extract_candidates(turn)

    assert candidates == (
        MemoryCandidate(subject="home city", content="Lives in Tehran."),
    )
    request = client_type.return_value.chat.call_args.kwargs
    assert request["messages"][1]["content"] == (
        "user:   I live in Tehran.  \nassistant: Thanks for telling me."
    )


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "{}",
        '[{"key": "city"}]',
        '[{"key": "city", "value": 3}]',
        '[{"key": "city", "value": "Tehran", "extra": true}]',
    ],
)
@patch("chat_buddy.chat.infrastructure.llm.ollama_gateway.Client")
def test_extract_candidates_rejects_malformed_provider_payload(
    client_type: Mock,
    payload: str,
) -> None:
    """Verify parsing and validation failures consume a processing attempt.

    Args:
        client_type:
            Mocked Ollama client constructor.
        payload:
            Malformed provider content.
    """

    client_type.return_value.chat.return_value = {
        "message": {"content": payload},
        "prompt_eval_count": 4,
        "eval_count": 2,
    }
    gateway = OllamaGateway(host="http://ollama.test")

    with pytest.raises((TypeError, ValueError)):
        gateway.extract_candidates(_memory_source())
