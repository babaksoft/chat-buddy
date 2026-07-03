import logging

from chat_buddy.domain.chat import ChatMessage
from chat_buddy.domain.context import ContextBuilder
from chat_buddy.domain.exceptions import ContextWindowExceededError
from chat_buddy.domain.tokenization import TokenCounter
from chat_buddy.infrastructure.config.settings import (
    MODEL_CONTEXT_WINDOW,
    PROMPT_OVERHEAD_TOKENS,
)

logger = logging.getLogger(__name__)


class DefaultContextBuilder(ContextBuilder):
    """
    Build the prompt context passed to the language model.
    """

    def __init__(
        self,
        token_counter: TokenCounter,
        model_context_window: int = MODEL_CONTEXT_WINDOW,
        prompt_overhead_tokens: int = PROMPT_OVERHEAD_TOKENS,
    ) -> None:
        self._token_counter = token_counter
        self._model_context_window = model_context_window
        self._prompt_overhead_tokens = prompt_overhead_tokens

    def build_context(
        self,
        messages: list[ChatMessage],
    ) -> list[ChatMessage]:
        """
        Return the conversation unchanged while logging
        prompt statistics.

        Args:
            messages:
                Current conversation history.

        Returns:
            Conversation history (without modification).
        """

        context_tokens = self._token_counter.count_tokens(messages)
        total_tokens = context_tokens + self._prompt_overhead_tokens
        utilization = total_tokens / self._model_context_window * 100

        if total_tokens > self._model_context_window:
            logger.warning(
                ("Context window exceeded: " "estimated_total_tokens=%d " "limit=%d"),
                total_tokens,
                self._model_context_window,
            )

            raise ContextWindowExceededError(
                "Conversation exceeds available context window."
            )

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
            self._prompt_overhead_tokens,
            total_tokens,
            utilization,
        )

        return messages
