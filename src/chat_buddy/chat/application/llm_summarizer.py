from chat_buddy.chat.domain import ChatMessage, LLMGateway


class LLMSummarizer:
    """
    Summarizer backed by an LLM.
    """

    def __init__(
        self,
        gateway: LLMGateway,
    ) -> None:
        """
        Initialize the summarizer.

        Args:
            gateway:
                Language model gateway.
        """

        self._gateway = gateway

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
