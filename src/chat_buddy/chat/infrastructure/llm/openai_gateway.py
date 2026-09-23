"""OpenAI Responses adapter for visible Chat responses."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from time import monotonic
from typing import Any, NoReturn

import openai

from chat_buddy.chat.domain import (
    ChatMessage,
    GenerationConfiguration,
    InvalidGenerationConfigurationError,
    ModelId,
    ProviderInvocationError,
)

logger = logging.getLogger(__name__)

_GPT_56_MODELS = frozenset({"gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.6-sol"})
_GPT_41_MODEL = "gpt-4.1-2025-04-14"
_MODEL_OUTPUT_LIMITS = {model: 128_000 for model in _GPT_56_MODELS} | {
    _GPT_41_MODEL: 32_768
}


class OpenAIGateway:
    """Generate complete and streaming responses with OpenAI Responses."""

    def __init__(self, api_key: str | None = None, client: Any | None = None) -> None:
        """Initialize the fixed-endpoint OpenAI adapter.

        Args:
            api_key:
                Explicit Chat-specific OpenAI credential.
            client:
                Optional SDK-compatible client for offline tests.

        Raises:
            ValueError:
                If neither an injected client nor a non-blank key is provided.
        """

        if client is None:
            if api_key is None or not api_key.strip():
                raise ValueError("A non-blank Chat OpenAI API key is required.")
            client = openai.OpenAI(
                api_key=api_key,
                base_url="https://api.openai.com/v1",
                timeout=openai.Timeout(
                    120.0,
                    connect=5.0,
                    read=120.0,
                    write=30.0,
                    pool=5.0,
                ),
                max_retries=2,
            )
        self._client = client

    def generate(
        self,
        messages: list[ChatMessage],
        model_id: ModelId,
        configuration: GenerationConfiguration,
    ) -> str:
        """Generate one complete response.

        Args:
            messages:
                Fully assembled provider-neutral prompt messages.
            model_id:
                Curated OpenAI model identifier.
            configuration:
                Validated effective Chat generation settings.

        Returns:
            Ordered text and refusal content.

        Raises:
            InvalidGenerationConfigurationError:
                If the model or configuration is outside the curated contract.
            ProviderInvocationError:
                If OpenAI fails or returns an invalid terminal response.
        """

        request = self._build_request(messages, model_id, configuration)
        started = monotonic()
        try:
            response = self._client.responses.create(**request)
        except openai.OpenAIError as error:
            self._raise_sdk_error(error, model_id, started)

        if getattr(response, "status", None) != "completed":
            self._raise_invalid_response(model_id, started)
        content = self._collect_response_content(response)
        if not content:
            self._raise_invalid_response(model_id, started)
        return content

    def generate_stream(
        self,
        messages: list[ChatMessage],
        model_id: ModelId,
        configuration: GenerationConfiguration,
    ) -> Iterator[str]:
        """Yield ordered non-empty response and refusal deltas.

        Args:
            messages:
                Fully assembled provider-neutral prompt messages.
            model_id:
                Curated OpenAI model identifier.
            configuration:
                Validated effective Chat generation settings.

        Yields:
            Ordered non-empty response text chunks.

        Raises:
            InvalidGenerationConfigurationError:
                If the model or configuration is outside the curated contract.
            ProviderInvocationError:
                If OpenAI fails or does not complete the stream successfully.
        """

        request = self._build_request(messages, model_id, configuration)
        started = monotonic()
        emitted = False
        completed = False
        try:
            streaming_client = self._client.with_options(max_retries=0)
            stream = streaming_client.responses.create(stream=True, **request)
            for event in stream:
                event_type = getattr(event, "type", None)
                if event_type in {
                    "response.output_text.delta",
                    "response.refusal.delta",
                }:
                    delta = getattr(event, "delta", "")
                    if isinstance(delta, str) and delta:
                        emitted = True
                        yield delta
                elif event_type == "response.completed":
                    response = getattr(event, "response", None)
                    completed = getattr(response, "status", None) == "completed"
                elif event_type in {
                    "response.failed",
                    "response.incomplete",
                    "response.cancelled",
                }:
                    self._raise_invalid_response(model_id, started)
        except openai.OpenAIError as error:
            self._raise_sdk_error(error, model_id, started)
        finally:
            close = getattr(locals().get("stream"), "close", None)
            if callable(close):
                close()

        if not completed or not emitted:
            self._raise_invalid_response(model_id, started)

    @staticmethod
    def _build_request(
        messages: list[ChatMessage],
        model_id: ModelId,
        configuration: GenerationConfiguration,
    ) -> dict[str, Any]:
        """Translate provider-neutral request data at the adapter boundary.

        Args:
            messages:
                Chat messages to translate.
            model_id:
                Curated OpenAI model identifier.
            configuration:
                Effective generation settings.

        Returns:
            Keyword arguments for ``responses.create``.

        Raises:
            InvalidGenerationConfigurationError:
                If the model or configuration is unsupported.
        """

        model = model_id.value
        if model not in _MODEL_OUTPUT_LIMITS:
            raise InvalidGenerationConfigurationError(
                f"OpenAI model '{model}' is not enabled."
            )
        if configuration.seed is not None:
            raise InvalidGenerationConfigurationError(
                "OpenAI response models do not support seed."
            )
        if model in _GPT_56_MODELS and (
            configuration.temperature is not None or configuration.top_p is not None
        ):
            raise InvalidGenerationConfigurationError(
                "GPT-5.6 response models support only max_output_tokens."
            )
        if (
            configuration.max_output_tokens is not None
            and configuration.max_output_tokens > _MODEL_OUTPUT_LIMITS[model]
        ):
            raise InvalidGenerationConfigurationError(
                f"OpenAI model '{model}' supports at most "
                f"{_MODEL_OUTPUT_LIMITS[model]} output tokens."
            )

        request: dict[str, Any] = {
            "model": model,
            "input": [
                {"role": message.role.value, "content": message.content}
                for message in messages
            ],
            "store": False,
        }
        if model in _GPT_56_MODELS:
            request["reasoning"] = {
                "effort": "none",
                "context": "current_turn",
            }
        for name in ("temperature", "top_p", "max_output_tokens"):
            value = getattr(configuration, name)
            if value is not None:
                request[name] = value
        return request

    @staticmethod
    def _collect_response_content(response: Any) -> str:
        """Concatenate output text and refusals in provider order.

        Args:
            response:
                Completed SDK response object.

        Returns:
            Concatenated visible content, or an empty string when malformed.
        """

        output = getattr(response, "output", None)
        if not isinstance(output, (list, tuple)):
            return ""
        parts: list[str] = []
        for item in output:
            contents = getattr(item, "content", None)
            if not isinstance(contents, (list, tuple)):
                return ""
            for content in contents:
                content_type = getattr(content, "type", None)
                if content_type == "output_text":
                    value = getattr(content, "text", "")
                elif content_type == "refusal":
                    value = getattr(content, "refusal", "")
                else:
                    continue
                if isinstance(value, str) and value:
                    parts.append(value)
        return "".join(parts)

    @staticmethod
    def _raise_sdk_error(
        error: openai.OpenAIError,
        model_id: ModelId,
        started: float,
    ) -> NoReturn:
        """Normalize an SDK failure without retaining unsafe provider detail.

        Args:
            error:
                OpenAI SDK exception.
            model_id:
                Selected curated model identifier.
            started:
                Monotonic invocation start time.

        Raises:
            ProviderInvocationError:
                Always, with a safe stable category.
        """

        if isinstance(
            error, (openai.AuthenticationError, openai.PermissionDeniedError)
        ):
            category = "provider_authentication_failed"
        elif isinstance(error, openai.RateLimitError):
            category = "provider_rate_limited"
        elif isinstance(error, openai.APITimeoutError):
            category = "provider_timeout"
        elif isinstance(error, (openai.APIConnectionError, openai.InternalServerError)):
            category = "provider_unavailable"
        else:
            category = "provider_request_rejected"

        logger.warning(
            "OpenAI invocation failed: category=%s status=%s request_id=%s "
            "model=%s duration_ms=%d",
            category,
            getattr(error, "status_code", None),
            getattr(error, "request_id", None),
            model_id,
            round((monotonic() - started) * 1000),
        )
        raise ProviderInvocationError(category) from None

    @staticmethod
    def _raise_invalid_response(model_id: ModelId, started: float) -> NoReturn:
        """Raise the safe category for malformed or unsuccessful output.

        Args:
            model_id:
                Selected curated model identifier.
            started:
                Monotonic invocation start time.

        Raises:
            ProviderInvocationError:
                Always, with the invalid-response category.
        """

        category = "provider_invalid_response"
        logger.warning(
            "OpenAI invocation failed: category=%s model=%s duration_ms=%d",
            category,
            model_id,
            round((monotonic() - started) * 1000),
        )
        raise ProviderInvocationError(category) from None
