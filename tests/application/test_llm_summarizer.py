from unittest.mock import Mock

from chat_buddy.application.llm_summarizer import (
    LLMSummarizer,
)
from chat_buddy.domain.chat import (
    ChatMessage,
    ChatRole,
)


def test_summarize_delegates_to_gateway() -> None:
    """
    Verify that summarization is delegated to
    the language model gateway.
    """

    gateway = Mock()
    gateway.summarize.return_value = "Conversation summary."

    summarizer = LLMSummarizer(
        gateway=gateway,
    )

    messages = [
        ChatMessage(
            role=ChatRole.USER,
            content="Hello.",
        ),
    ]

    summary = summarizer.summarize(messages)

    assert summary == "Conversation summary."

    gateway.summarize.assert_called_once_with(
        messages,
    )
