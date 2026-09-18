"""Common contract tests for response-provider adapters."""

from collections.abc import Iterator
from typing import cast
from unittest.mock import Mock

import pytest

from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    GenerationConfiguration,
    ModelId,
    ResponseGenerator,
)
from chat_buddy.chat.infrastructure.llm import OllamaGateway


class FakeResponseProvider:
    """Minimal second provider implementing only response generation."""

    def generate(
        self,
        messages: list[ChatMessage],
        model_id: ModelId,
        configuration: GenerationConfiguration,
    ) -> str:
        """Return the deterministic contract response.

        Args:
            messages:
                Conversation context supplied by Chat.
            model_id:
                Selected provider-local model identifier.
            configuration:
                Effective provider-neutral generation configuration.

        Returns:
            Complete deterministic response text.
        """

        return "Hello from contract."

    def generate_stream(
        self,
        messages: list[ChatMessage],
        model_id: ModelId,
        configuration: GenerationConfiguration,
    ) -> Iterator[str]:
        """Yield the deterministic contract response in chunks.

        Args:
            messages:
                Conversation context supplied by Chat.
            model_id:
                Selected provider-local model identifier.
            configuration:
                Effective provider-neutral generation configuration.

        Yields:
            Successive deterministic response chunks.
        """

        yield "Hello from "
        yield "contract."


@pytest.fixture(params=("ollama", "fake"), ids=("mocked-ollama", "fake-provider"))
def response_provider(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> ResponseGenerator:
    """Build each response adapter under the same provider-neutral contract.

    Args:
        request:
            Parameterized provider case selected by pytest.
        monkeypatch:
            Fixture used to replace the external Ollama client.

    Returns:
        Response provider under contract test.
    """

    provider_name = cast(str, request.param)
    if provider_name == "fake":
        return FakeResponseProvider()

    client = Mock()

    def chat(**kwargs: object) -> object:
        """Return synchronous or streaming mocked Ollama output.

        Args:
            **kwargs:
                Ollama request arguments.

        Returns:
            Mocked Ollama response matching the requested mode.
        """

        if kwargs.get("stream"):
            return iter(
                [
                    {"message": {"content": "Hello from "}},
                    {"message": {"content": "contract."}},
                ]
            )
        return {
            "message": {"content": "Hello from contract."},
            "prompt_eval_count": 1,
            "eval_count": 1,
        }

    client.chat.side_effect = chat
    client_type = Mock(return_value=client)
    monkeypatch.setattr(
        "chat_buddy.chat.infrastructure.llm.ollama_gateway.Client",
        client_type,
    )
    return OllamaGateway(host="http://ollama.test")


def test_response_provider_generates_complete_response(
    response_provider: ResponseGenerator,
) -> None:
    """Every response provider supports non-streaming generation."""

    response = response_provider.generate(
        [ChatMessage(role=ChatRole.USER, content="Hello")],
        ModelId("contract-model"),
        GenerationConfiguration(temperature=0.3),
    )

    assert response == "Hello from contract."


def test_response_provider_streams_response_chunks(
    response_provider: ResponseGenerator,
) -> None:
    """Every response provider supports ordered streaming generation."""

    chunks = response_provider.generate_stream(
        [ChatMessage(role=ChatRole.USER, content="Hello")],
        ModelId("contract-model"),
        GenerationConfiguration(temperature=0.3),
    )

    assert list(chunks) == ["Hello from ", "contract."]
