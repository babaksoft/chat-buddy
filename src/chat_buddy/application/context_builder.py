import logging

from chat_buddy.application.config import ContextBuilderConfig
from chat_buddy.application.llm_summarizer import LLMSummarizer
from chat_buddy.domain.chat import ChatMessage, ChatRole
from chat_buddy.domain.exceptions import ContextWindowExceededError
from chat_buddy.domain.summarization import Summarizer
from chat_buddy.domain.tokenization import TokenCounter
from chat_buddy.infrastructure.tokenization.mistral_token_counter import (
    MistralTokenCounter,
)

logger = logging.getLogger(__name__)


class DefaultContextBuilder:
    """
    Build the prompt context passed to the language model.
    """

    def __init__(
        self,
        token_counter: TokenCounter | None = None,
        summarizer: Summarizer | None = None,
        config: ContextBuilderConfig | None = None,
    ) -> None:
        """
        Initialize the context builder.

        Args:
            token_counter:
                Token counter.
            summarizer:
                Conversation Summarizer.
            config:
                Language model configuration.
        """

        self._token_counter = token_counter or MistralTokenCounter()
        self._summarizer = summarizer or LLMSummarizer()
        self._config = config or ContextBuilderConfig()

    def build_context(
        self,
        messages: list[ChatMessage],
    ) -> list[ChatMessage]:
        """
        Build a context suitable for the language model.

        Args:
            messages:
                Current conversation history.

        Returns:
            Context to send to the language model.

        Raises:
            ContextWindowExceededError:
                If the context exceeds the model window
                even after summarization.
        """

        context_tokens = self._token_counter.count_tokens(messages)
        total_tokens = context_tokens + self._config.prompt_overhead_tokens
        utilization = total_tokens / self._config.model_context_window * 100
        summary_threshold = (
            self._config.model_context_window * self._config.summary_trigger_ratio
        )

        if total_tokens <= summary_threshold:
            logger.info(
                (
                    "Context prepared: "
                    "messages=%d "
                    "context_tokens=%d "
                    "overhead_tokens=%d "
                    "estimated_total_tokens=%d "
                    "utilization=%.1f%%"
                ),
                len(messages),
                context_tokens,
                self._config.prompt_overhead_tokens,
                total_tokens,
                utilization,
            )

            return messages

        logger.info(
            (
                "Context exceeds summarization threshold: "
                "estimated_total_tokens=%d "
                "threshold=%d"
            ),
            total_tokens,
            int(summary_threshold),
        )

        rebuilt_context = self._summarize_context(messages)
        context_tokens = self._token_counter.count_tokens(rebuilt_context)
        total_tokens = context_tokens + self._config.prompt_overhead_tokens
        utilization = total_tokens / self._config.model_context_window * 100

        if total_tokens > self._config.model_context_window:
            logger.warning(
                (
                    "Context window exceeded after "
                    "summarization: "
                    "estimated_total_tokens=%d "
                    "limit=%d"
                ),
                total_tokens,
                self._config.model_context_window,
            )

            raise ContextWindowExceededError(
                "Conversation exceeds available context window after summarization."
            )

        logger.info(
            (
                "Context summarized: "
                "messages=%d "
                "context_tokens=%d "
                "overhead_tokens=%d "
                "estimated_total_tokens=%d "
                "utilization=%.1f%%"
            ),
            len(rebuilt_context),
            context_tokens,
            self._config.prompt_overhead_tokens,
            total_tokens,
            utilization,
        )

        return rebuilt_context

    def _summarize_context(
        self,
        messages: list[ChatMessage],
    ) -> list[ChatMessage]:
        """
        Summarize the oldest portion of a conversation.

        Args:
            messages:
                Current conversation context.

        Returns:
            Rebuilt context containing a system summary
            followed by the remaining recent messages.
        """

        split_index = max(1, len(messages) // 2)
        old_messages = messages[:split_index]
        recent_messages = messages[split_index:]

        logger.info(
            "Summarizing conversation: summary_messages=%d recent_messages=%d",
            len(old_messages),
            len(recent_messages),
        )

        summary = self._summarizer.summarize(old_messages)

        return [
            ChatMessage(
                role=ChatRole.SYSTEM,
                content=f"Conversation summary:\n\n{summary}",
            ),
            *recent_messages,
        ]
