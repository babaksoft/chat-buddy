from unittest.mock import Mock

from chat_buddy.application.context_builder import (
    DefaultContextBuilder,
)
from chat_buddy.domain.chat import (
    ChatMessage,
    ChatRole,
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
