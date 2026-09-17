import json
import logging
from collections.abc import Iterator
from typing import NoReturn

from ollama import Client, RequestError, ResponseError

from chat_buddy.chat.domain import (
    ChatMessage,
    ExtractedMemory,
    GenerationConfiguration,
    ModelId,
    ProviderInvocationError,
)
from chat_buddy.chat.infrastructure.config import settings
from chat_buddy.chat.prompts import (
    EXTRACT_MEMORY_PROMPT,
    GENERATE_TITLE_PROMPT,
    SUMMARIZE_PROMPT,
)

logger = logging.getLogger(__name__)


class OllamaGateway:
    """Ollama implementation of Chat response and utility capabilities."""

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
        model_id: ModelId | None = None,
        configuration: GenerationConfiguration | None = None,
    ) -> str:
        """
        Generate a response using Ollama.

        Args:
            messages:
                Current conversation history, including the last user message.

            model_id:
                Selected Ollama model, or the legacy configured model when omitted.

            configuration:
                Validated generation settings, or provider defaults when omitted.

        Returns:
            Generated response text.
        """

        model_name = self._resolve_model_name(model_id)
        logger.debug(
            "Generating response using model '%s'.",
            model_name,
        )

        response = self._chat(
            messages=[
                {
                    "role": message.role.value,
                    "content": message.content,
                }
                for message in messages
            ],
            model_name=model_name,
            configuration=configuration,
        )

        logger.debug(
            "Generated response (%d characters).",
            len(response),
        )

        return response

    def generate_stream(
        self,
        messages: list[ChatMessage],
        model_id: ModelId | None = None,
        configuration: GenerationConfiguration | None = None,
    ) -> Iterator[str]:
        """
        Generate a streaming response using Ollama.

        Args:
            messages:
                Current conversation history, including the last user message.

            model_id:
                Selected Ollama model, or the legacy configured model when omitted.

            configuration:
                Validated generation settings, or provider defaults when omitted.

        Yields:
            Response chunks as they are generated.
        """

        model_name = self._resolve_model_name(model_id)
        logger.debug(
            "Generating streaming response using model '%s'.",
            model_name,
        )

        formatted_messages = [
            {
                "role": message.role.value,
                "content": message.content,
            }
            for message in messages
        ]

        total_chunks = 0
        total_chars = 0

        try:
            options = self._build_options(configuration)
            if options:
                response_stream = self._client.chat(
                    model=model_name,
                    messages=formatted_messages,
                    stream=True,
                    options=options,
                )
            else:
                response_stream = self._client.chat(
                    model=model_name,
                    messages=formatted_messages,
                    stream=True,
                )

            for chunk in response_stream:
                content = chunk["message"]["content"]
                if content:
                    total_chunks += 1
                    total_chars += len(content)
                    yield content
        except (RequestError, ResponseError) as error:
            self._raise_provider_error(model_name, error)

        logger.debug(
            "Completed streaming response: chunks=%d chars=%d",
            total_chunks,
            total_chars,
        )

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
        configuration: GenerationConfiguration | None = None,
    ) -> str:
        """
        Generates a chat completion using given LLM model.

        Args:
            messages:
                Context that will be sent to the LLM.

            model_name:
                LLM model to use for chat completion.

            configuration:
                Validated generation settings, or provider defaults when omitted.

        Returns:
            LLM response as plain text.
        """

        try:
            options = self._build_options(configuration)
            if options:
                response = self._client.chat(
                    model=model_name,
                    messages=messages,
                    options=options,
                )
            else:
                response = self._client.chat(
                    model=model_name,
                    messages=messages,
                )
        except (RequestError, ResponseError) as error:
            self._raise_provider_error(model_name, error)

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

    def _resolve_model_name(self, model_id: ModelId | None) -> str:
        """Resolve a selected model while retaining the legacy default.

        Args:
            model_id:
                Selected provider-local model identifier.

        Returns:
            Ollama model name used for the request.
        """

        if model_id is None:
            return self._chat_model

        return model_id.value

    def _build_options(
        self,
        configuration: GenerationConfiguration | None,
    ) -> dict[str, float | int]:
        """Translate provider-neutral settings into Ollama options.

        Args:
            configuration:
                Validated effective generation configuration.

        Returns:
            Ollama options with unrequested values omitted.
        """

        if configuration is None:
            return {}

        options: dict[str, float | int] = {}
        if configuration.temperature is not None:
            options["temperature"] = configuration.temperature
        if configuration.top_p is not None:
            options["top_p"] = configuration.top_p
        if configuration.max_output_tokens is not None:
            options["num_predict"] = configuration.max_output_tokens
        if configuration.seed is not None:
            options["seed"] = configuration.seed
        return options

    def _raise_provider_error(
        self,
        model_name: str,
        error: RequestError | ResponseError,
    ) -> NoReturn:
        """Translate an Ollama SDK failure into a safe Chat exception.

        Args:
            model_name:
                Ollama model involved in the failed request.
            error:
                Provider-specific SDK failure.

        Raises:
            ProviderInvocationError:
                Always raised with the provider-specific failure chained.
        """

        raise ProviderInvocationError(
            f"Provider 'ollama' failed while invoking model '{model_name}'."
        ) from error
