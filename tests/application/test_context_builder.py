from unittest.mock import Mock

import pytest

from chat_buddy.application.config import ContextBuilderConfig
from chat_buddy.application.context_builder import (
    DefaultContextBuilder,
)
from chat_buddy.domain.chat import (
    ChatMessage,
    ChatRole,
)
from chat_buddy.domain.exceptions import (
    ContextWindowExceededError,
)


def test_build_context_returns_original_messages() -> None:
    """
    Verify that the default context builder returns
    the original message list unchanged.
    """

    token_counter = Mock()
    token_counter.count_tokens.return_value = 10
    builder = DefaultContextBuilder(token_counter=token_counter)

    messages = [
        ChatMessage(
            role=ChatRole.USER,
            content="Hello",
        ),
        ChatMessage(
            role=ChatRole.ASSISTANT,
            content="Hi!",
        ),
    ]

    context = builder.build_context(messages)

    assert context is messages


def test_build_context_returns_empty_list() -> None:
    """
    Verify that the default context builder supports
    an empty conversation.
    """

    token_counter = Mock()
    token_counter.count_tokens.return_value = 10
    builder = DefaultContextBuilder(token_counter=token_counter)

    context = builder.build_context([])

    assert context == []


def test_build_context_returns_messages_when_within_limit() -> None:
    """
    Verify that the default context builder works normally with
    small context.
    """

    messages = [
        ChatMessage(
            role=ChatRole.USER,
            content="Hello!",
        )
    ]

    counter = Mock()
    counter.count_tokens.return_value = 100
    config = ContextBuilderConfig(
        model_context_window=1_000,
        prompt_overhead_tokens=50,
    )

    builder = DefaultContextBuilder(
        token_counter=counter,
        config=config,
    )

    assert builder.build_context(messages) is messages


def test_build_context_summarizes_when_threshold_exceeded() -> None:
    """
    Verify that the oldest half of the conversation
    is summarized once the threshold is exceeded.
    """

    token_counter = Mock()
    token_counter.count_tokens.side_effect = [
        900,
        300,
    ]

    summarizer = Mock()
    summarizer.summarize.return_value = "Summary"

    builder = DefaultContextBuilder(
        token_counter=token_counter,
        summarizer=summarizer,
        config=ContextBuilderConfig(
            model_context_window=1_000,
            prompt_overhead_tokens=50,
            summary_trigger_ratio=0.8,
        ),
    )

    messages = [
        ChatMessage(ChatRole.USER, "A"),
        ChatMessage(ChatRole.ASSISTANT, "B"),
        ChatMessage(ChatRole.USER, "C"),
        ChatMessage(ChatRole.ASSISTANT, "D"),
        ChatMessage(ChatRole.USER, "E"),
        ChatMessage(ChatRole.ASSISTANT, "F"),
    ]

    context = builder.build_context(messages)

    summarizer.summarize.assert_called_once_with(
        messages[:3],
    )

    assert context[0].role == ChatRole.SYSTEM
    assert "Summary" in context[0].content

    assert context[1:] == messages[3:]


def test_build_context_raises_when_summary_still_too_large() -> None:
    """
    Verify that an exception is raised when the
    summarized context still exceeds the model
    context window.
    """

    token_counter = Mock()
    token_counter.count_tokens.side_effect = [
        900,
        980,
    ]

    summarizer = Mock()
    summarizer.summarize.return_value = "Summary"

    builder = DefaultContextBuilder(
        token_counter=token_counter,
        summarizer=summarizer,
        config=ContextBuilderConfig(
            model_context_window=1_000,
            prompt_overhead_tokens=50,
            summary_trigger_ratio=0.8,
        ),
    )

    messages = [
        ChatMessage(ChatRole.USER, "Hello"),
        ChatMessage(ChatRole.ASSISTANT, "Hi"),
    ]

    with pytest.raises(
        ContextWindowExceededError,
    ):
        builder.build_context(messages)
