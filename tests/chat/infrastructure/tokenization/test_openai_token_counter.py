"""Tests for conservative offline OpenAI Responses token counting."""

from chat_buddy.chat.domain import ChatMessage, ChatRole
from chat_buddy.chat.infrastructure.tokenization import OpenAITokenCounter


class CharacterEncoder:
    """Deterministic encoder returning one token per character."""

    def encode(self, text: str) -> list[int]:
        """Return one identifier per character.

        Args:
            text:
                Text to encode.

        Returns:
            Deterministic identifiers matching the text length.
        """

        return list(range(len(text)))


def test_empty_message_list_has_no_framing_cost() -> None:
    """No request messages produce a zero-token estimate."""

    counter = OpenAITokenCounter(CharacterEncoder())

    assert counter.count_tokens([]) == 0


def test_counter_applies_responses_framing_formula() -> None:
    """Role, content, per-message, and request framing are all counted."""

    messages = [
        ChatMessage(ChatRole.SYSTEM, "rules"),
        ChatMessage(ChatRole.USER, "hello"),
    ]
    counter = OpenAITokenCounter(CharacterEncoder())

    assert counter.count_tokens(messages) == (
        16 + (16 + len("system") + 5) + (16 + len("user") + 5)
    )
