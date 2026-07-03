from typing import Protocol

from chat_buddy.domain.chat import ChatMessage


class LLMGateway(Protocol):
    """
    Abstraction for language model interactions.
    """

    def generate(
        self,
        messages: list[ChatMessage],
    ) -> str:
        """
        Generate an assistant response.

        Args:
            messages:
                Conversation context.

        Returns:
            Assistant response.
        """

    def summarize(
        self,
        messages: list[ChatMessage],
    ) -> str:
        """
        Generate a summary of a conversation.

        Args:
            messages:
                Conversation messages.

        Returns:
            Conversation summary.
        """
