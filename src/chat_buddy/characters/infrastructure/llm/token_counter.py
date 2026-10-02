"""Deterministic conservative local prompt accounting."""

from chat_buddy.characters.domain.llm import PromptMessage


class Utf8TokenCounter:
    """Estimate one token per UTF-8 byte plus fixed message framing.

    This intentionally overestimates typical local text tokenization. It is a
    budgeting estimate, not measured provider usage or an exact tokenizer.
    """

    def count(self, messages: tuple[PromptMessage, ...]) -> int:
        """Count text bytes and reserve eight tokens per message plus eight.

        Args:
            messages:
                Complete ordered prompt messages.

        Returns:
            Deterministic conservative estimate including message framing.
        """

        return 8 + sum(
            8 + len(message.content.encode("utf-8")) + len(message.role)
            for message in messages
        )
