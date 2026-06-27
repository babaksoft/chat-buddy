import logging

from ollama import Client

from chat_buddy.domain.chat import ChatMessage
from chat_buddy.infrastructure.config.settings import (
    MODEL_NAME,
    OLLAMA_ENDPOINT_URL,
)
from chat_buddy.infrastructure.llm.base import LLMGateway

logger = logging.getLogger(__name__)


class OllamaGateway(LLMGateway):
    """
    Ollama-backed implementation of the LLM gateway.
    """

    def __init__(
        self,
        model_name: str = MODEL_NAME,
        host: str = OLLAMA_ENDPOINT_URL,
    ) -> None:
        """
        Initialize the Ollama gateway.

        Args:
            model_name:
                Name of the Ollama model.

            host:
                Ollama server endpoint.
        """

        self._model_name = model_name
        self._client = Client(host=host)

    def generate(
        self,
        messages: list[ChatMessage],
    ) -> str:
        """
        Generate a response using Ollama.

        Args:
            messages:
                Current conversation history, including the last user message.

        Returns:
            Generated response text.
        """

        logger.debug(
            "Generating response using model '%s'.",
            self._model_name,
        )

        response = self._client.chat(
            model=self._model_name,
            messages=[
                {
                    "role": message.role.value,
                    "content": message.content,
                }
                for message in messages
            ],
        )

        prompt_tokens = int(response["prompt_eval_count"])
        completion_tokens = int(response["eval_count"])
        logger.info(
            "LLM token usage: model=%s prompt=%d completion=%d total=%d",
            self._model_name,
            prompt_tokens,
            completion_tokens,
            prompt_tokens + completion_tokens,
        )

        content: str = str(response["message"]["content"])
        logger.debug(
            "Generated response (%d characters).",
            len(content),
        )

        return content
