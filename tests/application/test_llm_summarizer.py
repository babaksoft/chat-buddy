from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

from chat_buddy.chat.application.llm_summarizer import (
    LLMSummarizer,
)
from chat_buddy.chat.domain.chat import (
    ChatMessage,
    ChatRole,
)
from chat_buddy.chat.domain.context import CompletedTurn


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


def test_generate_summary_includes_prior_summary_and_exact_completed_turns() -> None:
    """Rolling generation formats durable prior state and exact new turns."""

    gateway = Mock()
    gateway.summarize.return_value = "Rolled conversation summary."
    turn = CompletedTurn(
        conversation_id=uuid4(),
        attempt_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        user_content="Question",
        assistant_content="Answer",
        completed_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    summarizer = LLMSummarizer(gateway=gateway)

    summary = summarizer.generate_summary("Earlier details", (turn,))

    assert summary == "Rolled conversation summary."
    gateway.summarize.assert_called_once_with(
        [
            ChatMessage(
                ChatRole.SYSTEM,
                "Previous conversation summary:\n\nEarlier details",
            ),
            ChatMessage(ChatRole.USER, "Question"),
            ChatMessage(ChatRole.ASSISTANT, "Answer"),
        ]
    )
