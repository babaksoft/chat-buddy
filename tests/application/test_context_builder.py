from unittest.mock import Mock

import pytest

from chat_buddy.chat.application.config import ContextBuilderConfig
from chat_buddy.chat.application.context_builder import DefaultContextBuilder
from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    ContextWindowExceededError,
    GenerationConfiguration,
    ModelDescriptor,
    ModelId,
    ProviderId,
)


def _model(token_counter: Mock, context_window: int = 1_000) -> ModelDescriptor:
    """Create a model descriptor for context-builder tests.

    Args:
        token_counter:
            Token counter attached to the model.
        context_window:
            Model context-window size.

    Returns:
        Test model descriptor.
    """

    return ModelDescriptor(
        provider_id=ProviderId("test"),
        id=ModelId("test-model"),
        display_name="Test model",
        context_window_tokens=context_window,
        supports_streaming=True,
        supported_generation_parameters=frozenset(),
        default_generation_configuration=GenerationConfiguration(),
        token_counter=token_counter,
        default_output_token_reserve=100,
    )


def _builder(summarizer: Mock | None = None) -> DefaultContextBuilder:
    """Create a context builder with stable non-model policy.

    Args:
        summarizer:
            Optional summarizer test double.

    Returns:
        Configured context builder.
    """

    return DefaultContextBuilder(
        summarizer=summarizer or Mock(),
        config=ContextBuilderConfig(
            prompt_overhead_tokens=50,
            summary_trigger_ratio=0.8,
        ),
    )


def test_build_context_uses_selected_model_token_counter() -> None:
    """Verify context estimation uses capabilities from the selected model."""

    counter = Mock()
    counter.count_tokens.return_value = 100
    messages = [ChatMessage(ChatRole.USER, "Hello")]

    context = _builder().build_context(messages, _model(counter))

    assert context is messages
    counter.count_tokens.assert_called_with(messages)


def test_build_context_uses_selected_model_window() -> None:
    """Verify a different model window changes summarization behavior."""

    messages = [
        ChatMessage(ChatRole.USER, "A"),
        ChatMessage(ChatRole.ASSISTANT, "B"),
        ChatMessage(ChatRole.USER, "C"),
        ChatMessage(ChatRole.ASSISTANT, "D"),
    ]
    small_counter = Mock()
    small_counter.count_tokens.side_effect = [800, 300, 300]
    large_counter = Mock()
    large_counter.count_tokens.return_value = 800
    summarizer = Mock()
    summarizer.summarize.return_value = "Summary"
    builder = _builder(summarizer)

    summarized = builder.build_context(messages, _model(small_counter, 1_000))
    unchanged = builder.build_context(messages, _model(large_counter, 2_000))

    assert summarized[0].role is ChatRole.SYSTEM
    assert "Summary" in summarized[0].content
    assert unchanged is messages


def test_build_context_raises_when_summary_exceeds_selected_model_window() -> None:
    """Verify the selected model limit governs the final context check."""

    counter = Mock()
    counter.count_tokens.side_effect = [900, 980]
    summarizer = Mock()
    summarizer.summarize.return_value = "Summary"
    messages = [
        ChatMessage(ChatRole.USER, "Hello"),
        ChatMessage(ChatRole.ASSISTANT, "Hi"),
    ]

    with pytest.raises(ContextWindowExceededError):
        _builder(summarizer).build_context(messages, _model(counter))
