from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
from typing import Protocol

from chat_buddy.chat.domain.exceptions import InvalidGenerationConfigurationError
from chat_buddy.chat.domain.tokenizer import TokenCounter


@dataclass(slots=True, frozen=True)
class ProviderId:
    """Stable identifier for a response provider."""

    value: str

    def __post_init__(self) -> None:
        """Validate the provider identifier.

        Raises:
            ValueError:
                If the identifier is empty or has surrounding whitespace.
        """

        if not self.value or self.value != self.value.strip():
            raise ValueError("Provider identifier must be non-empty and trimmed.")

    def __str__(self) -> str:
        """Return the identifier value.

        Returns:
            The stable provider identifier.
        """

        return self.value


@dataclass(slots=True, frozen=True)
class ModelId:
    """Stable provider-local identifier for a model."""

    value: str

    def __post_init__(self) -> None:
        """Validate the model identifier.

        Raises:
            ValueError:
                If the identifier is empty or has surrounding whitespace.
        """

        if not self.value or self.value != self.value.strip():
            raise ValueError("Model identifier must be non-empty and trimmed.")

    def __str__(self) -> str:
        """Return the identifier value.

        Returns:
            The stable model identifier.
        """

        return self.value


class GenerationParameter(str, Enum):
    """Provider-neutral generation parameters understood by Chat."""

    TEMPERATURE = "temperature"
    TOP_P = "top_p"
    MAX_OUTPUT_TOKENS = "max_output_tokens"
    SEED = "seed"


@dataclass(slots=True, frozen=True)
class GenerationConfiguration:
    """Non-secret provider-neutral generation settings.

    ``None`` means that the caller did not request a value. A registry can merge
    such a request with model defaults to produce the immutable effective
    configuration stored with a generation attempt.
    """

    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    seed: int | None = None

    def __post_init__(self) -> None:
        """Validate configured generation parameter values.

        Raises:
            InvalidGenerationConfigurationError:
                If a parameter is outside its provider-neutral valid range.
        """

        if self.temperature is not None and not 0 <= self.temperature <= 2:
            raise InvalidGenerationConfigurationError(
                "temperature must be between 0 and 2."
            )
        if self.top_p is not None and not 0 < self.top_p <= 1:
            raise InvalidGenerationConfigurationError(
                "top_p must be greater than 0 and at most 1."
            )
        if self.max_output_tokens is not None and self.max_output_tokens <= 0:
            raise InvalidGenerationConfigurationError(
                "max_output_tokens must be greater than 0."
            )
        if self.seed is not None and self.seed < 0:
            raise InvalidGenerationConfigurationError(
                "seed must be greater than or equal to 0."
            )

    @property
    def requested_parameters(self) -> frozenset[GenerationParameter]:
        """Return the parameters for which this configuration has values.

        Returns:
            Parameters explicitly represented by non-``None`` values.
        """

        return frozenset(
            GenerationParameter(field.name)
            for field in fields(self)
            if getattr(self, field.name) is not None
        )


@dataclass(slots=True, frozen=True)
class ProviderDescriptor:
    """User-presentable metadata for an enabled provider."""

    id: ProviderId
    display_name: str
    usage_notice: str | None = None

    def __post_init__(self) -> None:
        """Validate provider presentation metadata.

        Raises:
            ValueError:
                If the provider display name is blank.
        """

        if not self.display_name.strip():
            raise ValueError("Provider display name must be non-empty.")
        if self.usage_notice is not None and not self.usage_notice.strip():
            raise ValueError("Provider usage notice cannot be blank.")


@dataclass(slots=True, frozen=True)
class ModelDescriptor:
    """Immutable capabilities and defaults for a selectable model."""

    provider_id: ProviderId
    id: ModelId
    display_name: str
    context_window_tokens: int
    supports_streaming: bool
    supported_generation_parameters: frozenset[GenerationParameter]
    default_generation_configuration: GenerationConfiguration
    token_counter: TokenCounter
    default_output_token_reserve: int
    maximum_input_tokens: int | None = None
    maximum_output_tokens: int | None = None
    application_prompt_limit: int | None = None

    def __post_init__(self) -> None:
        """Validate model limits, presentation metadata, and defaults.

        Raises:
            ValueError:
                If the display name is blank or the context window is not positive.
            InvalidGenerationConfigurationError:
                If a default parameter is not supported by the model.
        """

        if not self.display_name.strip():
            raise ValueError("Model display name must be non-empty.")

        if self.context_window_tokens <= 0:
            raise ValueError("Model context window must be greater than 0.")
        if self.default_output_token_reserve <= 0:
            raise ValueError("Model output-token reserve must be greater than 0.")
        if self.default_output_token_reserve >= self.context_window_tokens:
            raise ValueError("Model output-token reserve must be below its window.")

        for name, value in (
            ("maximum input", self.maximum_input_tokens),
            ("maximum output", self.maximum_output_tokens),
            ("application prompt", self.application_prompt_limit),
        ):
            if value is not None and value <= 0:
                raise ValueError(f"Model {name} limit must be greater than 0.")
        if (
            self.maximum_input_tokens is not None
            and self.maximum_input_tokens > self.context_window_tokens
        ):
            raise ValueError("Model maximum input cannot exceed its context window.")
        if (
            self.maximum_output_tokens is not None
            and self.default_output_token_reserve > self.maximum_output_tokens
        ):
            raise ValueError("Model output-token reserve exceeds its maximum output.")

        unsupported_defaults = (
            self.default_generation_configuration.requested_parameters
            - self.supported_generation_parameters
        )
        if unsupported_defaults:
            names = ", ".join(sorted(item.value for item in unsupported_defaults))
            raise InvalidGenerationConfigurationError(
                f"Model defaults contain unsupported parameters: {names}."
            )

        configured_output = self.default_generation_configuration.max_output_tokens
        if (
            configured_output is not None
            and self.maximum_output_tokens is not None
            and configured_output > self.maximum_output_tokens
        ):
            raise InvalidGenerationConfigurationError(
                "Model default max_output_tokens exceeds its maximum output."
            )

    def prompt_token_capacity(self, output_reserve: int) -> int:
        """Return the model-specific prompt ceiling before fixed overhead.

        Args:
            output_reserve:
                Tokens reserved for the generated response.

        Returns:
            Smallest applicable provider, context, and application limit.
        """

        limits = [self.context_window_tokens - output_reserve]
        if self.maximum_input_tokens is not None:
            limits.append(self.maximum_input_tokens)
        if self.application_prompt_limit is not None:
            limits.append(self.application_prompt_limit)

        return min(limits)

    def output_token_reserve(self, configuration: GenerationConfiguration) -> int:
        """Return the deterministic reserve for one effective generation.

        Args:
            configuration:
                Effective generation configuration selected by the registry.

        Returns:
            Explicit output maximum or this model's positive fallback reserve.
        """

        return (
            configuration.max_output_tokens
            if configuration.max_output_tokens is not None
            else self.default_output_token_reserve
        )


class ProviderRegistry(Protocol):
    """Discover models and validate provider-neutral generation settings."""

    def list_providers(self) -> tuple[ProviderDescriptor, ...]:
        """Return enabled providers in presentation order.

        Returns:
            Immutable provider descriptors in presentation order.
        """

        ...

    def list_models(
        self, provider_id: ProviderId | None = None
    ) -> tuple[ModelDescriptor, ...]:
        """Return enabled models, optionally limited to one provider.

        Args:
            provider_id:
                Provider whose models to return, or ``None`` for all enabled models.

        Returns:
            Immutable model descriptors in presentation order.
        """

        ...

    def get_model(self, provider_id: ProviderId, model_id: ModelId) -> ModelDescriptor:
        """Return the descriptor for a registered provider and model.

        Args:
            provider_id:
                Stable identifier of the selected provider.
            model_id:
                Stable provider-local identifier of the selected model.

        Returns:
            Descriptor for the selected registered model.
        """

        ...

    def get_default_model(self) -> ModelDescriptor:
        """Return the configured default response model.

        Returns:
            Descriptor for the default response model.
        """

        ...

    def resolve_generation_configuration(
        self,
        model: ModelDescriptor,
        requested: GenerationConfiguration,
    ) -> GenerationConfiguration:
        """Validate a request and merge it with the model defaults.

        Args:
            model:
                Selected registered model descriptor.
            requested:
                Provider-neutral settings requested for the generation.

        Returns:
            Validated effective non-secret generation configuration.

        Raises:
            InvalidGenerationConfigurationError:
                If the request contains a parameter unsupported by the selected model.
        """

        ...
