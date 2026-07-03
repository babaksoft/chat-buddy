from unittest.mock import Mock

import pytest

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

    builder = DefaultContextBuilder(
        token_counter=counter,
        model_context_window=1_000,
        prompt_overhead_tokens=50,
    )

    assert builder.build_context(messages) is messages


def test_build_context_raises_when_limit_exceeded() -> None:
    """
    Verify that the default context builder raises domain-specific
    error when context is too large.
    """

    messages = [
        ChatMessage(
            role=ChatRole.USER,
            content="Hello!",
        )
    ]

    counter = Mock()
    counter.count_tokens.return_value = 980

    builder = DefaultContextBuilder(
        token_counter=counter,
        model_context_window=1_000,
        prompt_overhead_tokens=50,
    )

    with pytest.raises(
        ContextWindowExceededError,
    ):
        builder.build_context(messages)
