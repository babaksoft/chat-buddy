from abc import ABC, abstractmethod

from chat_buddy.domain.chat import ChatMessage


class LLMGateway(ABC):
    """Abstract interface for LLM integrations."""

    @abstractmethod
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
