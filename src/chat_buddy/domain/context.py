from typing import Protocol

from chat_buddy.domain.chat import ChatMessage


class ContextBuilder(Protocol):
    def build_context(
        self,
        messages: list[ChatMessage],
    ) -> list[ChatMessage]:
        """
        Build context from conversation history.

        Args:
            messages:
                Current conversation history.

        Returns:
            Adjusted context from conversation history.
        """
