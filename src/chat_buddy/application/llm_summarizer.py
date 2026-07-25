from chat_buddy.domain import ChatMessage, LLMGateway
from chat_buddy.infrastructure.llm import OllamaGateway


class LLMSummarizer:
    """
    Summarizer backed by an LLM.
    """

    def __init__(
        self,
        gateway: LLMGateway | None = None,
    ) -> None:
        """
        Initialize the summarizer.

        Args:
            gateway:
                Language model gateway.
        """

        self._gateway = gateway or OllamaGateway()

    def summarize(
        self,
        messages: list[ChatMessage],
    ) -> str:
        """
        Produce a summary using the language model.

        Args:
            messages:
                Conversation messages.

        Returns:
            Conversation summary.
        """

        return self._gateway.summarize(messages)
