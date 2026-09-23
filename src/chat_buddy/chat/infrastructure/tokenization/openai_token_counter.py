"""Offline token estimation for OpenAI Responses requests."""

from collections.abc import Sequence
from typing import Protocol

import tiktoken

from chat_buddy.chat.domain import ChatMessage


class TextEncoder(Protocol):
    """Encode text into provider tokenizer identifiers."""

    def encode(self, text: str) -> Sequence[int]:
        """Encode text.

        Args:
            text:
                Text to encode.

        Returns:
            Token identifiers for the text.
        """

        ...


class OpenAITokenCounter:
    """Conservatively estimate framed OpenAI Responses input tokens."""

    def __init__(self, encoder: TextEncoder | None = None) -> None:
        """Initialize the counter with the fixed OpenAI encoding.

        Args:
            encoder:
                Optional injected encoder used by deterministic tests.
        """

        self._encoder = encoder

    def count_tokens(self, messages: list[ChatMessage]) -> int:
        """Count encoded role/content tokens plus conservative framing.

        Args:
            messages:
                Provider-neutral messages in request order.

        Returns:
            Zero for no messages, otherwise the framed token estimate.
        """

        if not messages:
            return 0
        if self._encoder is None:
            self._encoder = tiktoken.get_encoding("o200k_base")
        return 16 + sum(
            16
            + len(self._encoder.encode(message.role.value))
            + len(self._encoder.encode(message.content))
            for message in messages
        )
