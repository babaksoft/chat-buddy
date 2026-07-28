from typing import Protocol

from chat_buddy.domain.chat import ChatMessage
from chat_buddy.domain.extracted_memory import ExtractedMemory


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

    def generate_title(
        self,
        messages: list[ChatMessage],
    ) -> str:
        """
        Generate a short title for a conversation.

        Args:
            messages:
                Conversation messages.

        Returns:
            Conversation title.
        """

    def extract_memories(
        self,
        messages: list[ChatMessage],
    ) -> list[ExtractedMemory]:
        """
        Extract long-term user memories from a conversation.

        Args:
            messages:
                Conversation messages.

        Returns:
            Extracted memories.
        """
