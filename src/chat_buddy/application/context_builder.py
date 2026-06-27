import logging

from chat_buddy.domain.chat import ChatMessage
from chat_buddy.domain.context import ContextBuilder
from chat_buddy.domain.tokenization import TokenCounter
from chat_buddy.infrastructure.config.settings import (
    MODEL_CONTEXT_WINDOW,
    MODEL_RESERVED_TOKENS,
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
    ) -> None:
        self._token_counter = token_counter
        self._model_context_window = model_context_window

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

        prompt_tokens = self._token_counter.count_tokens(messages)
        total_tokens = prompt_tokens + MODEL_RESERVED_TOKENS
        utilization = total_tokens / self._model_context_window * 100

        logger.info(
            (
                "Context prepared: "
                "messages=%d "
                "prompt_tokens=%d "
                "reserved_tokens=%d "
                "estimated_total_tokens=%d "
                "utilization=%.1f%%"
            ),
            len(messages),
            prompt_tokens,
            MODEL_RESERVED_TOKENS,
            total_tokens,
            utilization,
        )

        return messages
