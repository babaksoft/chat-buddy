from typing import Protocol

from chat_buddy.domain.chat import ChatMessage


class LLMGateway(Protocol):
    """Abstract interface for LLM integrations."""

    def generate(
        self,
        messages: list[ChatMessage],
    ) -> str:
        """
        Generate a response from the language model.

        Args:
            messages:
                Current conversation history, including the last user message.

        Returns:
            Generated model response.
        """
