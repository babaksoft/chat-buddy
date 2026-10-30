"""Configured model resolution with independent capability bindings."""

from pydantic import ValidationError

from chat_buddy.characters.domain import (
    EffectiveGeneration,
    EvolutionGateway,
    GenerationCapability,
    GenerationConfiguration,
    MemoryExtractionGateway,
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
        memory_extractions: dict[str, MemoryExtractionGateway] | None = None,
        defaults: dict[GenerationCapability, tuple[str, str]] | None = None,
        evolutions: dict[str, EvolutionGateway] | None = None,
    ) -> None:
        """Capture configured models and separate capability implementations.

        Args:
            models:
                Models in selection order.
            responses:
                Response providers keyed by provider identifier.
            summaries:
                Summary providers keyed by provider identifier.
            memory_extractions:
                Memory-extraction providers keyed by provider identifier.
            counters:
                Token estimators keyed by provider identifier.
            defaults:
                Independently selected default model for each operation.
            evolutions:
                Evolution proposal providers keyed by provider identifier.

        Raises:
            ValueError:
                If models are duplicated or lack required bindings.
        """

        self._models = {(item.provider, item.model): item for item in models}
        self._responses = dict(responses)
        self._summaries = dict(summaries)
        self._memory_extractions = dict(memory_extractions or {})
        self._evolutions = dict(evolutions or {})
        self._counters = dict(counters)
        self._defaults = dict(defaults or {})

        if len(self._models) != len(models):
            raise ValueError("Duplicate configured model.")
        for item in models:
            if (
                item.provider not in counters
                or ("response" in item.capabilities and item.provider not in responses)
                or ("summary" in item.capabilities and item.provider not in summaries)
                or (
                    "memory_extraction" in item.capabilities
                    and item.provider not in self._memory_extractions
                )
                or (
                    "evolution" in item.capabilities
                    and item.provider not in self._evolutions
                )
            ):
                raise ValueError("Missing model capability binding.")

        for capability in self._defaults:
            if capability not in {
                "response",
                "summary",
                "memory_extraction",
                "evolution",
            }:
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
        capability: GenerationCapability,
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
        capability: GenerationCapability,
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
            raise ModelResolutionError("No default model configured.")
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

    def memory_extraction_gateway(self, provider: str) -> MemoryExtractionGateway:
        """Select a memory-extraction implementation.

        Args:
            provider:
                Configured provider key.

        Returns:
            Structured extraction adapter.

        Raises:
            UnsupportedGenerationError:
                If no memory-extraction adapter is configured.
        """

        if provider not in self._memory_extractions:
            raise UnsupportedGenerationError(
                "Memory-extraction capability is unavailable."
            )

        return self._memory_extractions[provider]

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

    def evolution_gateway(self, provider: str) -> EvolutionGateway:
        """Select a structured evolution implementation.

        Args:
            provider:
                Configured provider key.

        Returns:
            Structured evolution adapter.

        Raises:
            UnsupportedGenerationError:
                If no evolution adapter is configured.
        """

        if provider not in self._evolutions:
            raise UnsupportedGenerationError("Evolution capability is unavailable.")
        return self._evolutions[provider]

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
