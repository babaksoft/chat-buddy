import json
import logging

from ollama import Client

from chat_buddy.domain import ChatMessage, ExtractedMemory
from chat_buddy.infrastructure.config import settings
from chat_buddy.prompts import (
    EXTRACT_MEMORY_PROMPT,
    GENERATE_TITLE_PROMPT,
    SUMMARIZE_PROMPT,
)

logger = logging.getLogger(__name__)


class OllamaGateway:
    """
    Ollama-backed implementation of the LLM gateway.
    """

    def __init__(
        self,
        model_name: str | None = None,
        host: str | None = None,
    ) -> None:
        """
        Initialize the Ollama gateway.

        Args:
            model_name:
                Name of the Ollama model.

            host:
                Ollama server endpoint.
        """

        self._utility_model = settings.UTILITY_MODEL
        self._chat_model = model_name or settings.CHAT_MODEL
        ollama_host = host or settings.OLLAMA_ENDPOINT_URL
        self._client = Client(host=ollama_host)

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
            self._chat_model,
        )

        response = self._chat(
            messages=[
                {
                    "role": message.role.value,
                    "content": message.content,
                }
                for message in messages
            ],
            model_name=self._chat_model,
        )

        logger.debug(
            "Generated response (%d characters).",
            len(response),
        )

        return response

    def summarize(
        self,
        messages: list[ChatMessage],
    ) -> str:
        """
        Summarize a conversation.

        Args:
            messages:
                Conversation messages.

        Returns:
            Conversation summary.
        """

        logger.debug(
            "Generating conversation summary using model '%s'.",
            self._utility_model,
        )

        conversation = "\n".join(
            f"{message.role.value}: {message.content}" for message in messages
        )

        response = self._chat(
            messages=[
                {
                    "role": "system",
                    "content": SUMMARIZE_PROMPT,
                },
                {
                    "role": "user",
                    "content": conversation,
                },
            ],
            model_name=self._utility_model,
        )

        logger.info(
            "Generated conversation summary (%d characters).",
            len(response),
        )

        return response

    def generate_title(
        self,
        messages: list[ChatMessage],
    ) -> str:
        """
        Generate a short title for a conversation.

        Args:
            messages:
                Conversation messages.

        Returns:
            Generated title text.
        """

        logger.debug(
            "Generating conversation title using model '%s'.",
            self._utility_model,
        )

        conversation = "\n".join(
            f"{message.role.value}: {message.content}" for message in messages
        )

        response = self._chat(
            messages=[
                {
                    "role": "system",
                    "content": GENERATE_TITLE_PROMPT,
                },
                {
                    "role": "user",
                    "content": conversation,
                },
            ],
            model_name=self._utility_model,
        )

        logger.info(
            "Generated conversation title (%d characters).",
            len(response),
        )

        return response

    def extract_memories(
        self,
        messages: list[ChatMessage],
    ) -> list[ExtractedMemory]:
        """
        Extract long-term user memories from a conversation.

        Args:
            messages:
                Conversation messages.

        Returns:
            Extracted memories.
        """

        logger.debug(
            "Extracting memories using model '%s'.",
            self._utility_model,
        )

        conversation = "\n".join(
            f"{message.role.value}: {message.content}"
            for message in messages
            if message.role.value != "assistant"
        )

        response = self._chat(
            messages=[
                {
                    "role": "system",
                    "content": EXTRACT_MEMORY_PROMPT,
                },
                {
                    "role": "user",
                    "content": conversation,
                },
            ],
            model_name=self._utility_model,
        )

        try:
            payload = json.loads(response)

            memories = [
                ExtractedMemory(
                    key=item["key"],
                    value=item["value"],
                )
                for item in payload
            ]

        except (
            json.JSONDecodeError,
            KeyError,
            TypeError,
        ):
            logger.warning(
                "Failed to parse extracted memories.",
            )
            return []

        logger.info(
            "Memory extraction completed: extracted=%d",
            len(memories),
        )

        return memories

    def _chat(
        self,
        messages: list[dict[str, str]],
        model_name: str,
    ) -> str:
        """
        Generates a chat completion using given LLM model.

        Args:
            messages:
                Context that will be sent to the LLM.

            model_name:
                LLM model to use for chat completion.

        Returns:
            LLM response as plain text.
        """

        response = self._client.chat(
            model=model_name,
            messages=messages,
        )

        prompt_tokens = int(response["prompt_eval_count"])
        completion_tokens = int(response["eval_count"])

        logger.info(
            "LLM token usage: model=%s prompt=%d completion=%d total=%d",
            model_name,
            prompt_tokens,
            completion_tokens,
            prompt_tokens + completion_tokens,
        )

        return str(response["message"]["content"])
