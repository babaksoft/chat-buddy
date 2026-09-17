from typing import Protocol

from chat_buddy.chat.domain.chat import ChatMessage
from chat_buddy.chat.domain.providers import ModelDescriptor


class ContextBuilder(Protocol):
    """Abstraction for adjusting conversation context."""

    def build_context(
        self,
        messages: list[ChatMessage],
        model: ModelDescriptor,
    ) -> list[ChatMessage]:
        """
        Build context from conversation history.

        Args:
            messages:
                Current conversation history.
            model:
                Selected model capabilities used for context budgeting.

        Returns:
            Adjusted context from conversation history.
        """
