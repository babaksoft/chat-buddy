from typing import Protocol

from chat_buddy.domain.chat import ChatMessage


class Summarizer(Protocol):
    """
    Summarizes a conversation.
    """

    def summarize(
        self,
        messages: list[ChatMessage],
    ) -> str:
        """
        Produce a summary of the supplied conversation.

        Args:
            messages:
                Conversation messages.

        Returns:
            Conversation summary.
        """
