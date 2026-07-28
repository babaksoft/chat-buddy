import logging

from chat_buddy.application.config import ContextBuilderConfig
from chat_buddy.application.llm_summarizer import LLMSummarizer
from chat_buddy.domain import (
    ChatMessage,
    ChatRole,
    ContextWindowExceededError,
    Summarizer,
    TokenCounter,
)
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

        total_tokens = self._get_token_count(messages)
        summary_threshold = (
            self._config.model_context_window * self._config.summary_trigger_ratio
        )

        if total_tokens <= summary_threshold:
            self._log_context("Context prepared", messages)

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
        total_tokens = self._get_token_count(rebuilt_context)

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

        self._log_context("Context summarized", rebuilt_context)

        return rebuilt_context

    def _log_context(self, message: str, context: list[ChatMessage]) -> None:
        """
        Calculate and log current context utilization.

        Args:
            message:
                Message thet describes current operation.

            context:
                Current conversation context.
        """

        context_tokens = self._token_counter.count_tokens(context)
        total_tokens = context_tokens + self._config.prompt_overhead_tokens
        utilization = total_tokens / self._config.model_context_window * 100

        logger.info(
            (
                f"{message}: "
                "messages=%d "
                "context_tokens=%d "
                "overhead_tokens=%d "
                "estimated_total_tokens=%d "
                "utilization=%.1f%%"
            ),
            len(context),
            context_tokens,
            self._config.prompt_overhead_tokens,
            total_tokens,
            utilization,
        )

    def _get_token_count(self, context: list[ChatMessage]) -> int:
        """
        Count tokens in a conversation.

        Args:
            context:
                Current conversation context.

        Returns:
            Estimated token count.
        """

        context_tokens = self._token_counter.count_tokens(context)

        return context_tokens + self._config.prompt_overhead_tokens

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

        system_messages = [
            message for message in messages if message.role == ChatRole.SYSTEM
        ]
        dialogue = [message for message in messages if message.role != ChatRole.SYSTEM]

        if not dialogue:
            return messages

        split_index = max(1, len(dialogue) // 2)
        old_messages = dialogue[:split_index]
        recent_messages = dialogue[split_index:]

        logger.info(
            (
                "Summarizing conversation: system_messages=%d "
                "summary_messages=%d recent_messages=%d"
            ),
            len(system_messages),
            len(old_messages),
            len(recent_messages),
        )

        summary = self._summarizer.summarize(old_messages)

        return [
            *system_messages,
            ChatMessage(
                role=ChatRole.SYSTEM,
                content=f"Conversation summary:\n\n{summary}",
            ),
            *recent_messages,
        ]
