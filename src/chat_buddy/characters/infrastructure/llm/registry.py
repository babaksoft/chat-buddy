"""Configured model resolution with independent capability bindings."""

from typing import Literal

from pydantic import ValidationError

from chat_buddy.characters.domain import (
    EffectiveGeneration,
    GenerationConfiguration,
    ModelDescriptor,
    ModelResolutionError,
    ResponseGateway,
    SummaryGateway,
    TokenCounter,
    UnsupportedGenerationError,
)


class ConfiguredModelRegistry:
    """Resolve models using configured model registry."""

    def __init__(
        self,
        models: tuple[ModelDescriptor, ...],
        responses: dict[str, ResponseGateway],
        summaries: dict[str, SummaryGateway],
        counters: dict[str, TokenCounter],
        defaults: dict[Literal["response", "summary"], tuple[str, str]] | None = None,
    ) -> None:
        """Capture configured models and separate capability implementations.

        Args:
            models:
                Models in selection order.
            responses:
                Response providers keyed by provider identifier.
            summaries:
                Summary providers keyed independently.
            counters:
                Token estimators keyed by provider identifier.
            defaults:
                Independently selected default model for each operation.

        Raises:
            ValueError:
                If models are duplicated or lack required bindings.
        """

        self._models = {(item.provider, item.model): item for item in models}
        self._responses = dict(responses)
        self._summaries = dict(summaries)
        self._counters = dict(counters)
        self._defaults = dict(defaults or {})

        if len(self._models) != len(models):
            raise ValueError("Duplicate configured model.")
        for item in models:
            if (
                item.provider not in counters
                or ("response" in item.capabilities and item.provider not in responses)
                or ("summary" in item.capabilities and item.provider not in summaries)
            ):
                raise ValueError("Missing model capability binding.")

        for capability in self._defaults:
            if capability not in {"response", "summary"}:
                raise ValueError("Unknown default capability.")

            self.resolve_default(capability)

    def list_models(self) -> tuple[ModelDescriptor, ...]:
        """List configured models in selection order.

        Returns:
            Immutable model descriptors.
        """

        return tuple(self._models.values())

    def resolve(
        self,
        provider: str,
        model: str,
        capability: Literal["response", "summary"],
        requested: GenerationConfiguration,
    ) -> EffectiveGeneration:
        """Merge supported overrides with model defaults and reserve output.

        Args:
            provider:
                Configured provider key.
            model:
                Configured local model name.
            capability:
                Required operation.
            requested:
                Validated parameter overrides.

        Returns:
            Immutable effective settings.

        Raises:
            ModelResolutionError:
                If the model is unknown.
            UnsupportedGenerationError:
                If the operation, parameters, or reserve cannot be supported.
        """

        descriptor = self._get_model(provider, model)
        values = descriptor.defaults.model_dump(exclude_none=True)
        values.update(requested.model_dump(exclude_none=True))
        values.setdefault("max_output_tokens", descriptor.output_tokens)

        try:
            configuration = GenerationConfiguration.model_validate(values)
            return EffectiveGeneration(
                model=descriptor,
                configuration=configuration,
                capability=capability,
                input_tokens=descriptor.context_tokens - values["max_output_tokens"],
            )
        except ValidationError:
            raise UnsupportedGenerationError(
                "Unsupported generation settings or capability."
            ) from None

    def resolve_default(
        self,
        capability: Literal["response", "summary"],
        requested: GenerationConfiguration | None = None,
    ) -> EffectiveGeneration:
        """Resolve the configured default for one independent operation.

        Args:
            capability:
                Required operation.
            requested:
                Optional overrides for this generation.

        Returns:
            Default model and effective settings.

        Raises:
            ModelResolutionError:
                If no default selection exists.
            UnsupportedGenerationError:
                If the default cannot support this operation or settings.
        """

        if capability not in self._defaults:
            raise ModelResolutionError("No default Characters model configured.")
        provider, model = self._defaults[capability]
        return self.resolve(
            provider, model, capability, requested or GenerationConfiguration()
        )

    def response_gateway(self, provider: str) -> ResponseGateway:
        """Select a response implementation.

        Args:
            provider:
                Configured provider key.

        Returns:
            Streaming response adapter.

        Raises:
            UnsupportedGenerationError:
                If no response adapter is configured.
        """

        if provider not in self._responses:
            raise UnsupportedGenerationError("Response capability is unavailable.")

        return self._responses[provider]

    def summary_gateway(self, provider: str) -> SummaryGateway:
        """Select a summary implementation.

        Args:
            provider:
                Configured provider key.

        Returns:
            Summary adapter.

        Raises:
            UnsupportedGenerationError:
                If no summary adapter is configured.
        """

        if provider not in self._summaries:
            raise UnsupportedGenerationError("Summary capability is unavailable.")

        return self._summaries[provider]

    def token_counter(self, provider: str) -> TokenCounter:
        """Select a provider's deterministic prompt estimator.

        Args:
            provider:
                Configured provider key.

        Returns:
            Token counter.

        Raises:
            ModelResolutionError:
                If the provider is unknown.
        """

        if provider not in self._counters:
            raise ModelResolutionError("Unknown token counter provider.")

        return self._counters[provider]

    def _get_model(self, provider: str, model: str) -> ModelDescriptor:
        """Look up an exact configured provider/model pair.

        Args:
            provider:
                Provider key.
            model:
                Model name.

        Returns:
            Configured descriptor.

        Raises:
            ModelResolutionError:
                If the pair is unknown.
        """

        if (provider, model) not in self._models:
            raise ModelResolutionError("Unknown provider/model selection.")

        return self._models[provider, model]
