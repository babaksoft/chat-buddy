"""Tests for conservative offline Ollama token counting."""

from collections.abc import Sequence
from unittest.mock import Mock, patch

from chat_buddy.chat.domain import ChatMessage, ChatRole
from chat_buddy.chat.infrastructure.tokenization import OllamaTokenCounter


class CharacterEncoder:
    """Encode each character as one deterministic test token."""

    def encode(self, text: str, *, add_special_tokens: bool = False) -> Sequence[int]:
        """Return one token identifier per character.

        Args:
            text:
                Text to encode.
            add_special_tokens:
                Whether boundary tokens were requested.

        Returns:
            Deterministic character positions.

        Raises:
            AssertionError:
                If production code requests tokenizer-specific special tokens.
        """

        assert not add_special_tokens
        return tuple(range(len(text)))


def test_count_tokens_accounts_for_roles_content_and_message_framing() -> None:
    """Count deterministic content with conservative request framing."""

    counter = OllamaTokenCounter(CharacterEncoder())
    messages = [
        ChatMessage(role=ChatRole.USER, content="Hello"),
        ChatMessage(role=ChatRole.ASSISTANT, content="Hi"),
    ]

    assert counter.count_tokens([]) == 0
    assert counter.count_tokens(messages) == 8 + 8 + 4 + 5 + 8 + 9 + 2


def test_count_tokens_increases_with_content() -> None:
    """Longer content produces a larger estimate with the same framing."""

    counter = OllamaTokenCounter(CharacterEncoder())
    short = [ChatMessage(role=ChatRole.USER, content="Hello")]
    long = [
        ChatMessage(
            role=ChatRole.USER,
            content="Hello, this is a considerably longer message.",
        )
    ]

    assert counter.count_tokens(long) > counter.count_tokens(short)


@patch(
    "chat_buddy.chat.infrastructure.tokenization.ollama_token_counter."
    "AutoTokenizer.from_pretrained"
)
def test_tokenizer_is_loaded_lazily_and_cached(loader: Mock) -> None:
    """Defer the pinned tokenizer download and reuse the loaded encoder.

    Args:
        loader:
            Patched Hugging Face tokenizer loader.
    """

    loader.return_value = CharacterEncoder()
    counter = OllamaTokenCounter()
    message = [ChatMessage(role=ChatRole.USER, content="Hello")]

    loader.assert_not_called()
    counter.count_tokens(message)
    counter.count_tokens(message)

    loader.assert_called_once_with(
        OllamaTokenCounter.TOKENIZER_NAME,
        revision=OllamaTokenCounter.TOKENIZER_REVISION,
    )
