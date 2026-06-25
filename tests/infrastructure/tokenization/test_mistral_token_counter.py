import pytest

from chat_buddy.domain.chat import (
    ChatMessage,
    ChatRole,
)
from chat_buddy.infrastructure.tokenization.mistral_token_counter import (
    MistralTokenCounter,
)


@pytest.fixture(scope="session")
def counter() -> MistralTokenCounter:
    return MistralTokenCounter()


def test_count_tokens_empty_messages(counter: MistralTokenCounter) -> None:
    """
    Verify token counting handles an empty
    message list.
    """

    count = counter.count_tokens([])

    assert count == 0


def test_count_tokens_single_message(counter: MistralTokenCounter) -> None:
    """
    Verify token count is positive for a
    single message.
    """

    messages = [
        ChatMessage(
            role=ChatRole.USER,
            content="Hello world",
        )
    ]

    count = counter.count_tokens(messages)

    assert count > 0


def test_count_tokens_increases_with_content(counter: MistralTokenCounter) -> None:
    """
    Verify token count grows as content
    size increases.
    """

    short_messages = [
        ChatMessage(
            role=ChatRole.USER,
            content="Hello",
        )
    ]

    long_messages = [
        ChatMessage(
            role=ChatRole.USER,
            content=(
                "Hello "
                "this is a considerably longer "
                "message containing more words."
            ),
        )
    ]

    short_count = counter.count_tokens(
        short_messages,
    )

    long_count = counter.count_tokens(
        long_messages,
    )

    assert long_count > short_count


def test_count_tokens_multiple_messages(counter: MistralTokenCounter) -> None:
    """
    Verify multiple messages contribute
    to the total token count.
    """

    single = [
        ChatMessage(
            role=ChatRole.USER,
            content="Hello",
        )
    ]

    multiple = [
        ChatMessage(
            role=ChatRole.USER,
            content="Hello",
        ),
        ChatMessage(
            role=ChatRole.ASSISTANT,
            content="Hi there",
        ),
    ]

    single_count = counter.count_tokens(single)
    multiple_count = counter.count_tokens(multiple)

    assert multiple_count > single_count
