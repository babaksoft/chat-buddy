from collections.abc import Iterator
from dataclasses import FrozenInstanceError

import pytest

from chat_buddy.chat.domain import (
    ChatMessage,
    GenerationConfiguration,
    GenerationParameter,
    InvalidGenerationConfigurationError,
    ModelDescriptor,
    ModelId,
    ProviderId,
    ResponseGenerator,
)


class FakeTokenCounter:
    """Minimal token counter used by model descriptor tests."""

    def count_tokens(self, messages: list[ChatMessage]) -> int:
        """Count messages as tokens for descriptor contract tests.

        Args:
            messages:
                Messages whose synthetic token count is requested.

        Returns:
            Number of supplied messages.
        """

        return len(messages)


class FakeResponseGenerator:
    """Response-only provider; utility capabilities are intentionally absent."""

    def generate(
        self,
        messages: list[ChatMessage],
        model_id: ModelId,
        configuration: GenerationConfiguration,
    ) -> str:
        """Return a fixed response for protocol conformance tests.

        Args:
            messages:
                Conversation context, unused by this fake.
            model_id:
                Selected model identifier, unused by this fake.
            configuration:
                Effective settings, unused by this fake.

        Returns:
            Fixed fake response text.
        """

        return "response"

    def generate_stream(
        self,
        messages: list[ChatMessage],
        model_id: ModelId,
        configuration: GenerationConfiguration,
    ) -> Iterator[str]:
        """Yield a fixed response for protocol conformance tests.

        Args:
            messages:
                Conversation context, unused by this fake.
            model_id:
                Selected model identifier, unused by this fake.
            configuration:
                Effective settings, unused by this fake.

        Yields:
            Fixed fake response text.
        """

        yield "response"


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"temperature": -0.1}, "temperature"),
        ({"temperature": 2.1}, "temperature"),
        ({"top_p": 0}, "top_p"),
        ({"top_p": 1.1}, "top_p"),
        ({"max_output_tokens": 0}, "max_output_tokens"),
        ({"seed": -1}, "seed"),
    ],
)
def test_generation_configuration_rejects_invalid_values(
    values: dict[str, float | int], message: str
) -> None:
    """Verify that out-of-range generation parameters are rejected.

    Args:
        values:
            Invalid constructor arguments under test.
        message:
            Expected parameter name in the validation error.
    """

    with pytest.raises(InvalidGenerationConfigurationError, match=message):
        GenerationConfiguration(**values)  # type: ignore[arg-type]


def test_generation_configuration_is_immutable() -> None:
    """Verify that generation configuration values cannot be reassigned."""

    configuration = GenerationConfiguration(temperature=0.5)

    with pytest.raises(FrozenInstanceError):
        configuration.temperature = 1  # type: ignore[misc]


def test_model_descriptor_rejects_unsupported_default_parameter() -> None:
    """Verify that model defaults must be part of its supported parameters."""

    with pytest.raises(
        InvalidGenerationConfigurationError, match="unsupported.*temperature"
    ):
        ModelDescriptor(
            provider_id=ProviderId("local"),
            id=ModelId("chat-model"),
            display_name="Chat model",
            context_window_tokens=8192,
            supports_streaming=True,
            supported_generation_parameters=frozenset(
                {GenerationParameter.MAX_OUTPUT_TOKENS}
            ),
            default_generation_configuration=GenerationConfiguration(temperature=0.5),
            token_counter=FakeTokenCounter(),
            default_output_token_reserve=1024,
        )


def test_model_descriptor_uses_explicit_or_fallback_output_reserve() -> None:
    """Every model provides a positive reserve when callers omit a maximum."""

    model = ModelDescriptor(
        provider_id=ProviderId("local"),
        id=ModelId("chat-model"),
        display_name="Chat model",
        context_window_tokens=8192,
        supports_streaming=True,
        supported_generation_parameters=frozenset(
            {GenerationParameter.MAX_OUTPUT_TOKENS}
        ),
        default_generation_configuration=GenerationConfiguration(),
        token_counter=FakeTokenCounter(),
        default_output_token_reserve=1024,
    )

    assert model.output_token_reserve(GenerationConfiguration()) == 1024
    assert (
        model.output_token_reserve(GenerationConfiguration(max_output_tokens=256))
        == 256
    )


@pytest.mark.parametrize("reserve", (0, -1, 8192))
def test_model_descriptor_rejects_invalid_output_reserve(reserve: int) -> None:
    """Output reserve must be positive and leave prompt capacity.

    Args:
        reserve:
            Invalid reserve under test.
    """

    with pytest.raises(ValueError, match="output-token reserve"):
        ModelDescriptor(
            provider_id=ProviderId("local"),
            id=ModelId("chat-model"),
            display_name="Chat model",
            context_window_tokens=8192,
            supports_streaming=True,
            supported_generation_parameters=frozenset(),
            default_generation_configuration=GenerationConfiguration(),
            token_counter=FakeTokenCounter(),
            default_output_token_reserve=reserve,
        )


def test_response_provider_does_not_need_utility_capabilities() -> None:
    """Verify that response providers need not implement utility operations."""

    provider: ResponseGenerator = FakeResponseGenerator()

    response = provider.generate([], ModelId("chat-model"), GenerationConfiguration())

    assert response == "response"
    assert not hasattr(provider, "generate_title")
    assert not hasattr(provider, "summarize")
    assert not hasattr(provider, "extract_memories")
