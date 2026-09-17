from collections.abc import Iterator
from typing import Protocol

from chat_buddy.chat.domain.chat import ChatMessage
from chat_buddy.chat.domain.extracted_memory import ExtractedMemory
from chat_buddy.chat.domain.providers import (
    GenerationConfiguration,
    ModelId,
    ProviderId,
)


class ResponseGenerator(Protocol):
    """Generate visible assistant responses for a selected model."""

    def generate(
        self,
        messages: list[ChatMessage],
        model_id: ModelId,
        configuration: GenerationConfiguration,
    ) -> str:
        """Generate one complete assistant response.

        Args:
            messages:
                Conversation context for the response.
            model_id:
                Stable identifier of the selected provider model.
            configuration:
                Validated effective generation configuration.

        Returns:
            Complete assistant response text.
        """

        ...

    def generate_stream(
        self,
        messages: list[ChatMessage],
        model_id: ModelId,
        configuration: GenerationConfiguration,
    ) -> Iterator[str]:
        """Yield chunks of one assistant response.

        Args:
            messages:
                Conversation context for the response.
            model_id:
                Stable identifier of the selected provider model.
            configuration:
                Validated effective generation configuration.

        Yields:
            Successive response text chunks.
        """

        ...


class TitleGenerator(Protocol):
    """Generate short conversation titles independently of responses."""

    def generate_title(self, messages: list[ChatMessage]) -> str:
        """Generate a title from conversation messages.

        Args:
            messages: Conversation messages to title.

        Returns:
            Generated conversation title.
        """

        ...


class SummaryGenerator(Protocol):
    """Generate conversation summaries independently of responses."""

    def summarize(self, messages: list[ChatMessage]) -> str:
        """Summarize conversation messages.

        Args:
            messages: Conversation messages to summarize.

        Returns:
            Generated conversation summary.
        """

        ...


class MemoryExtractor(Protocol):
    """Extract durable memory candidates independently of responses."""

    def extract_memories(self, messages: list[ChatMessage]) -> list[ExtractedMemory]:
        """Extract memory candidates from conversation messages.

        Args:
            messages: Conversation messages to inspect.

        Returns:
            Extracted durable memory candidates.
        """

        ...


class ResponseGatewayResolver(Protocol):
    """Resolve a response adapter without exposing provider infrastructure."""

    def resolve(self, provider_id: ProviderId) -> ResponseGenerator:
        """Return the response adapter registered for a provider.

        Args:
            provider_id: Stable identifier of the selected provider.

        Returns:
            Response generator registered for the provider.
        """

        ...
