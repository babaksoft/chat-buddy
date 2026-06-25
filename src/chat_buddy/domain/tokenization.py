from dataclasses import dataclass
from typing import Protocol

from chat_buddy.domain.chat import ChatMessage


@dataclass(slots=True, frozen=True)
class TokenUsage:
    """
    Token usage statistics for a model interaction.
    """

    prompt_tokens: int
    completion_tokens: int


class TokenCounter(Protocol):
    """
    Count tokens in chat messages.
    """

    def count_tokens(
        self,
        messages: list[ChatMessage],
    ) -> int:
        """
        Count tokens in a message list.

        Args:
            messages:
                Messages to count.

        Returns:
            Total token count.
        """
