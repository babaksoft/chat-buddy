"""Offline token estimation for curated Ollama models."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, cast

from transformers import AutoTokenizer

from chat_buddy.chat.domain import ChatMessage


class _OllamaTextEncoder(Protocol):
    """Encode text without adding model-specific special tokens."""

    def encode(self, text: str, *, add_special_tokens: bool = False) -> Sequence[int]:
        """Encode text into tokenizer identifiers.

        Args:
            text:
                Text to encode.
            add_special_tokens:
                Whether to add tokenizer-specific boundary tokens.

        Returns:
            Token identifiers for the text.
        """

        ...


class OllamaTokenCounter:
    """Conservatively estimate Ollama prompt tokens with a Llama tokenizer."""

    TOKENIZER_NAME = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
    TOKENIZER_REVISION = "26d45f26ea2159eee86ccb80db170f755c1b3d95"

    def __init__(self, encoder: _OllamaTextEncoder | None = None) -> None:
        """Initialize the counter without performing network access.

        Args:
            encoder:
                Optional injected encoder used by deterministic tests.
        """

        self._encoder = encoder

    def count_tokens(self, messages: list[ChatMessage]) -> int:
        """Count encoded role and content tokens plus conservative framing.

        Args:
            messages:
                Provider-neutral messages in request order.

        Returns:
            Zero for no messages, otherwise the framed token estimate.
        """

        if not messages:
            return 0

        encoder = self._get_encoder()
        return 8 + sum(
            8
            + len(encoder.encode(message.role.value, add_special_tokens=False))
            + len(encoder.encode(message.content, add_special_tokens=False))
            for message in messages
        )

    def _get_encoder(self) -> _OllamaTextEncoder:
        """Load and cache the pinned public tokenizer on first use.

        Returns:
            Cached tokenizer-compatible text encoder.
        """

        if self._encoder is None:
            self._encoder = cast(
                _OllamaTextEncoder,
                AutoTokenizer.from_pretrained(
                    self.TOKENIZER_NAME,
                    revision=self.TOKENIZER_REVISION,
                ),
            )
        return self._encoder
