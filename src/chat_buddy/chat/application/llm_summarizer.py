from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    CompletedTurn,
    SummaryGenerator,
)


class LLMSummarizer:
    """
    Summarizer backed by an LLM.
    """

    def __init__(
        self,
        gateway: SummaryGenerator,
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

    def generate_summary(
        self,
        prior_summary: str | None,
        turns: tuple[CompletedTurn, ...],
    ) -> str:
        """Generate a rolling summary from durable prior state and new turns.

        Args:
            prior_summary:
                Existing active summary text, when replacing a version.
            turns:
                Newly covered completed turns in chronological order.

        Returns:
            Replacement summary text from the utility provider.
        """

        messages: list[ChatMessage] = []
        if prior_summary is not None:
            messages.append(
                ChatMessage(
                    ChatRole.SYSTEM,
                    f"Previous conversation summary:\n\n{prior_summary}",
                )
            )
        for turn in turns:
            messages.extend(turn.messages)

        return self._gateway.summarize(messages)
