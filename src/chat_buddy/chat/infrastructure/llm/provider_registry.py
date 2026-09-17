"""Configured response-provider discovery and resolution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields, replace

from chat_buddy.chat.domain import (
    GenerationConfiguration,
    InvalidGenerationConfigurationError,
    ModelDescriptor,
    ModelId,
    ProviderDescriptor,
    ProviderId,
    ResponseGenerator,
    UnknownModelError,
    UnknownProviderError,
)


class StaticProviderRegistry:
    """Expose statically configured providers and immutable model descriptors."""

    def __init__(
        self,
        providers: Sequence[ProviderDescriptor],
        models: Sequence[ModelDescriptor],
        default_provider_id: ProviderId,
        default_model_id: ModelId,
    ) -> None:
        """Initialize and validate a static registry.

        Args:
            providers:
                Enabled providers in presentation order.
            models:
                Enabled models in presentation order.
            default_provider_id:
                Provider selected when no persisted selection exists.
            default_model_id:
                Provider-local model selected by default.

        Raises:
            ValueError:
                If identifiers are duplicated or a model has no provider.
            UnknownModelError:
                If the configured default model is not registered.
            UnknownProviderError:
                If the configured default provider is not registered.
        """

        self._providers = tuple(providers)
        self._models = tuple(models)
        self._providers_by_id = self._index_providers(self._providers)
        self._models_by_key = self._index_models(self._models)
        self._default_model = self.get_model(
            default_provider_id,
            default_model_id,
        )

    def list_providers(self) -> tuple[ProviderDescriptor, ...]:
        """Return enabled providers in presentation order.

        Returns:
            Immutable provider descriptors in presentation order.
        """

        return self._providers

    def list_models(
        self, provider_id: ProviderId | None = None
    ) -> tuple[ModelDescriptor, ...]:
        """Return enabled models, optionally restricted to one provider.

        Args:
            provider_id:
                Provider whose models to return, or ``None`` for every model.

        Returns:
            Immutable model descriptors in presentation order.

        Raises:
            UnknownProviderError:
                If the requested provider is not registered.
        """

        if provider_id is None:
            return self._models

        self._get_provider(provider_id)
        return tuple(
            model for model in self._models if model.provider_id == provider_id
        )

    def get_model(self, provider_id: ProviderId, model_id: ModelId) -> ModelDescriptor:
        """Return a registered model descriptor.

        Args:
            provider_id:
                Stable identifier of the selected provider.
            model_id:
                Stable provider-local identifier of the selected model.

        Returns:
            Descriptor for the selected model.

        Raises:
            UnknownModelError:
                If the model is not registered for the provider.
            UnknownProviderError:
                If the provider is not registered.
        """

        self._get_provider(provider_id)
        try:
            return self._models_by_key[(provider_id, model_id)]
        except KeyError as error:
            raise UnknownModelError(
                f"Model '{model_id}' is not registered for provider "
                f"'{provider_id}'."
            ) from error

    def get_default_model(self) -> ModelDescriptor:
        """Return the configured default response model.

        Returns:
            Descriptor for the default model.
        """

        return self._default_model

    def resolve_generation_configuration(
        self,
        model: ModelDescriptor,
        requested: GenerationConfiguration,
    ) -> GenerationConfiguration:
        """Validate requested settings and merge them with model defaults.

        Args:
            model:
                Selected registered model descriptor.
            requested:
                Provider-neutral generation settings requested by the caller.

        Returns:
            Validated effective generation settings.

        Raises:
            InvalidGenerationConfigurationError:
                If the model is stale or a requested parameter is unsupported.
            UnknownModelError:
                If the selected model is not registered.
        """

        registered_model = self.get_model(model.provider_id, model.id)
        if registered_model != model:
            raise InvalidGenerationConfigurationError(
                "Model descriptor does not match the registered descriptor."
            )

        unsupported = (
            requested.requested_parameters
            - registered_model.supported_generation_parameters
        )
        if unsupported:
            names = ", ".join(sorted(item.value for item in unsupported))
            raise InvalidGenerationConfigurationError(
                f"Model '{model.id}' does not support: {names}."
            )

        overrides = {
            field.name: value
            for field in fields(requested)
            if (value := getattr(requested, field.name)) is not None
        }
        return replace(
            registered_model.default_generation_configuration,
            **overrides,
        )

    def _get_provider(self, provider_id: ProviderId) -> ProviderDescriptor:
        """Return a registered provider descriptor.

        Args:
            provider_id:
                Provider identifier to look up.

        Returns:
            Matching provider descriptor.

        Raises:
            UnknownProviderError:
                If the provider is not registered.
        """

        try:
            return self._providers_by_id[provider_id]
        except KeyError as error:
            raise UnknownProviderError(
                f"Provider '{provider_id}' is not registered."
            ) from error

    @staticmethod
    def _index_providers(
        providers: tuple[ProviderDescriptor, ...],
    ) -> dict[ProviderId, ProviderDescriptor]:
        """Index providers while rejecting duplicate identifiers.

        Args:
            providers:
                Providers to index.

        Returns:
            Providers keyed by stable identifier.

        Raises:
            ValueError:
                If a provider identifier appears more than once.
        """

        indexed = {provider.id: provider for provider in providers}
        if len(indexed) != len(providers):
            raise ValueError("Provider identifiers must be unique.")
        return indexed

    def _index_models(
        self,
        models: tuple[ModelDescriptor, ...],
    ) -> dict[tuple[ProviderId, ModelId], ModelDescriptor]:
        """Index models while validating provider ownership and uniqueness.

        Args:
            models:
                Models to index.

        Returns:
            Models keyed by provider and model identifier.

        Raises:
            UnknownProviderError:
                If a model references an unregistered provider.
            ValueError:
                If a provider-local model identifier appears more than once.
        """

        for model in models:
            self._get_provider(model.provider_id)
        indexed = {(model.provider_id, model.id): model for model in models}
        if len(indexed) != len(models):
            raise ValueError("Model identifiers must be unique within a provider.")
        return indexed


class StaticResponseGatewayResolver:
    """Resolve configured response adapters by stable provider identifier."""

    def __init__(self, gateways: Mapping[ProviderId, ResponseGenerator]) -> None:
        """Initialize the resolver.

        Args:
            gateways:
                Response adapters keyed by provider identifier.
        """

        self._gateways = dict(gateways)

    def resolve(self, provider_id: ProviderId) -> ResponseGenerator:
        """Return the response adapter registered for a provider.

        Args:
            provider_id:
                Stable identifier of the selected provider.

        Returns:
            Configured response adapter.

        Raises:
            UnknownProviderError:
                If the provider has no response adapter.
        """

        try:
            return self._gateways[provider_id]
        except KeyError as error:
            raise UnknownProviderError(
                f"Provider '{provider_id}' has no response adapter."
            ) from error
