"""Ollama implementation of the Characters response and summary contracts."""

from collections.abc import Iterator
from typing import Any

from ollama import Client

from chat_buddy.characters.domain import (
    EffectiveGeneration,
    InvalidProviderResponseError,
    PromptMessage,
    ProviderInvocationError,
    UnsupportedGenerationError,
)


class OllamaGateway:
    """Invoke local models without owning Characters business prompts."""

    def __init__(self, host: str, client: Client | None = None) -> None:
        """Initialize a local client only when composition is explicitly requested.

        Args:
            host:
                Characters-owned Ollama endpoint.
            client:
                Optional injected client for isolated adapter tests.
        """

        self._client = client if client is not None else Client(host=host)

    def stream(
        self, messages: tuple[PromptMessage, ...], generation: EffectiveGeneration
    ) -> Iterator[str]:
        """Yield response text and close the underlying stream on every exit.

        Args:
            messages:
                Application-assembled prompt.
            generation:
                Effective response settings.

        Yields:
            Nonempty text fragments in provider order.

        Raises:
            UnsupportedGenerationError:
                If this is not an Ollama response request.
            ProviderInvocationError:
                If the provider fails before or after partial output.
        """

        self._validate(generation, "response")
        stream: Any = None
        try:
            stream = self._client.chat(
                model=generation.model.model,
                messages=[message.model_dump() for message in messages],
                options=self._options(generation),
                stream=True,
            )
            for chunk in stream:
                content = self._content(chunk)
                if content:
                    yield content
        except InvalidProviderResponseError:
            raise
        except Exception:  # noqa: BLE001
            raise ProviderInvocationError(
                "Characters local response generation failed."
            ) from None
        finally:
            if stream is not None:
                close = getattr(stream, "close", None)
                if close is not None:
                    try:
                        close()
                    except Exception:  # noqa: BLE001
                        raise ProviderInvocationError(
                            "Characters local stream closure failed."
                        ) from None

    def summarize(
        self, messages: tuple[PromptMessage, ...], generation: EffectiveGeneration
    ) -> str:
        """Generate and validate plain summary text.

        Args:
            messages:
                Application-assembled summary prompt.
            generation:
                Effective summary settings.

        Returns:
            Trimmed nonempty summary text.

        Raises:
            UnsupportedGenerationError:
                If this is not an Ollama summary request.
            InvalidProviderResponseError:
                If summary text is malformed or empty.
            ProviderInvocationError:
                If the local provider fails.
        """

        self._validate(generation, "summary")
        try:
            response = self._client.chat(
                model=generation.model.model,
                messages=[message.model_dump() for message in messages],
                options=self._options(generation),
                stream=False,
            )
            content = self._content(response).strip()
            if not content:
                raise InvalidProviderResponseError(
                    "Characters summary output was empty."
                )
            return content
        except InvalidProviderResponseError:
            raise
        except Exception:  # noqa: BLE001
            raise ProviderInvocationError(
                "Characters local summary generation failed."
            ) from None

    def _validate(self, generation: EffectiveGeneration, capability: str) -> None:
        """Reject selections intended for another adapter or operation.

        Args:
            generation:
                Effective settings.
            capability:
                Invoked operation.

        Raises:
            UnsupportedGenerationError:
                If the adapter cannot execute this selection.
        """

        if generation.model.provider != "ollama" or generation.capability != capability:
            raise UnsupportedGenerationError(
                "Incompatible Characters Ollama selection."
            )

    def _options(self, generation: EffectiveGeneration) -> dict[str, Any]:
        """Translate all effective settings, including context and output limits.

        Args:
            generation:
                Validated effective settings.

        Returns:
            Ollama request options.
        """

        values = generation.configuration.model_dump(exclude_none=True)
        values["num_predict"] = values.pop("max_output_tokens")
        values["num_ctx"] = generation.model.context_tokens
        return values

    def _content(self, response: Any) -> str:
        """Read content from SDK responses or dictionary test doubles.

        Args:
            response:
                Provider response or stream chunk.

        Returns:
            Exact response text.

        Raises:
            InvalidProviderResponseError:
                If the provider payload does not contain text.
        """

        try:
            content = response["message"]["content"]
        except (KeyError, TypeError, AttributeError):
            raise InvalidProviderResponseError(
                "Characters provider returned malformed text."
            ) from None
        if not isinstance(content, str):
            raise InvalidProviderResponseError(
                "Characters provider returned malformed text."
            )
        return content
