from collections.abc import Iterator
from typing import Protocol

from chat_buddy.chat.domain.chat import ChatMessage
from chat_buddy.chat.domain.extracted_memory import ExtractedMemory


class LLMGateway(Protocol):
    """
    Temporary compatibility contract for the pre-Stage 2 Ollama adapter.

    New provider adapters should implement the capability-specific protocols in
    ``chat_buddy.chat.domain.gateways`` instead. This combined contract remains
    until application composition is migrated in later Stage 2 slices.
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

    def generate_stream(
        self,
        messages: list[ChatMessage],
    ) -> Iterator[str]:
        """
        Generate an assistant response with streaming.

        Args:
            messages:
                Conversation context.

        Yields:
            Response chunks as they are generated.
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
