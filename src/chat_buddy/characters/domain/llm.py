"""Provider-neutral Characters generation values and narrow capabilities."""

from collections.abc import Iterator
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PromptMessage(BaseModel):
    """One ordered provider input, independent of persisted messages.

    Attributes:
        role:
            Provider-neutral speaker role.
        content:
            Exact prompt text.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["system", "user", "assistant"] = Field(description="Speaker role.")
    content: str = Field(description="Exact prompt text.")


class GenerationConfiguration(BaseModel):
    """Requested or effective non-secret generation settings.

    Attributes:
        max_output_tokens:
            Positive output limit, or model default when absent.
        temperature:
            Sampling temperature, or model default when absent.
        top_p:
            Nucleus sampling probability, or model default when absent.
        seed:
            Reproducibility hint, or provider default when absent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    max_output_tokens: int | None = Field(
        default=None, gt=0, description="Output limit."
    )
    temperature: float | None = Field(
        default=None, ge=0, le=2, description="Temperature."
    )
    top_p: float | None = Field(
        default=None, gt=0, le=1, description="Sampling probability."
    )
    seed: int | None = Field(default=None, ge=0, description="Sampling seed.")


class ModelCapabilities(BaseModel):
    """Configured local model capabilities and deterministic budget.

    Attributes:
        provider:
            Stable provider key.
        model:
            Provider-local model name.
        context_tokens:
            Configured context window including output.
        output_tokens:
            Default output reserve and enforced output limit.
        capabilities:
            Supported response and summary operations.
        parameters:
            Supported optional generation parameters.
        defaults:
            Model defaults merged with each request.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    provider: str = Field(min_length=1, description="Provider key.")
    model: str = Field(min_length=1, description="Local model name.")
    context_tokens: int = Field(gt=1, description="Total context budget.")
    output_tokens: int = Field(gt=0, description="Default output reserve.")
    capabilities: frozenset[Literal["response", "summary"]] = Field(
        description="Supported operations."
    )
    parameters: frozenset[Literal["temperature", "top_p", "seed"]] = Field(
        default=frozenset(), description="Optional supported parameters."
    )
    defaults: GenerationConfiguration = Field(
        default_factory=GenerationConfiguration, description="Model defaults."
    )

    @model_validator(mode="after")
    def validate_budget(self) -> Self:
        """Validate defaults and reserve against declared capabilities.

        Returns:
            Validated model descriptor.

        Raises:
            ValueError:
                If defaults or reserve contradict model capabilities.
        """

        output = self.defaults.max_output_tokens or self.output_tokens
        if max(output, self.output_tokens) >= self.context_tokens:
            raise ValueError("Output reserve must be below the context window.")
        if (
            set(self.defaults.model_dump(exclude_none=True))
            - {"max_output_tokens"}
            - self.parameters
        ):
            raise ValueError("Model defaults contain unsupported parameters.")
        return self


class EffectiveGeneration(BaseModel):
    """Immutable resolved settings suitable for generation provenance.

    Attributes:
        model:
            Selected model capabilities.
        configuration:
            Merged validated settings with an explicit output limit.
        capability:
            Selected operation.
        input_tokens:
            Remaining input capacity after output reservation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: ModelCapabilities = Field(description="Selected capabilities.")
    configuration: GenerationConfiguration = Field(description="Effective settings.")
    capability: Literal["response", "summary"] = Field(
        description="Selected operation."
    )
    input_tokens: int = Field(gt=0, description="Input capacity.")

    @model_validator(mode="after")
    def validate_effective(self) -> Self:
        """Check that the snapshot matches the declared model budget.

        Returns:
            Validated snapshot.

        Raises:
            ValueError:
                If the operation, parameters, or budget are unsupported.
        """

        output = self.configuration.max_output_tokens
        if self.capability not in self.model.capabilities or output is None:
            raise ValueError("Unsupported capability or missing output reserve.")
        if self.input_tokens != self.model.context_tokens - output:
            raise ValueError("Input capacity must match the output reserve.")
        if (
            set(self.configuration.model_dump(exclude_none=True))
            - {"max_output_tokens"}
            - self.model.parameters
        ):
            raise ValueError("Unsupported generation parameters.")
        return self


class ResponseGateway(Protocol):
    """Stream persona text without requiring summary support."""

    def stream(
        self, messages: tuple[PromptMessage, ...], generation: EffectiveGeneration
    ) -> Iterator[str]:
        """Stream text; closing the iterator releases provider resources.

        Args:
            messages:
                Ordered assembled prompt.
            generation:
                Resolved response settings.

        Returns:
            Text iterator whose failures use Characters domain errors.
        """

        ...


class SummaryGateway(Protocol):
    """Generate summary text from an application-assembled prompt."""

    def summarize(
        self, messages: tuple[PromptMessage, ...], generation: EffectiveGeneration
    ) -> str:
        """Return a nonempty summary without constructing business prompts.

        Args:
            messages:
                Ordered summary prompt.
            generation:
                Resolved summary settings.

        Returns:
            Generated summary text.
        """

        ...


class TokenCounter(Protocol):
    """Account for text and message framing before provider invocation."""

    def count(self, messages: tuple[PromptMessage, ...]) -> int:
        """Estimate prompt tokens deterministically.

        Args:
            messages:
                Complete ordered provider input.

        Returns:
            Nonnegative prompt token estimate including framing.
        """

        ...


class ModelResolver(Protocol):
    """Resolve selectable models and effective generation settings."""

    def list_models(self) -> tuple[ModelCapabilities, ...]:
        """List configured models.

        Returns:
            Immutable ordered descriptors.
        """

        ...

    def resolve(
        self,
        provider: str,
        model: str,
        capability: Literal["response", "summary"],
        requested: GenerationConfiguration,
    ) -> EffectiveGeneration:
        """Resolve a supported operation and merge model defaults.

        Args:
            provider:
                Provider key.
            model:
                Local model name.
            capability:
                Required operation.
            requested:
                Requested overrides.

        Returns:
            Effective configuration and budget.
        """

        ...

    def resolve_default(
        self,
        capability: Literal["response", "summary"],
        requested: GenerationConfiguration | None = None,
    ) -> EffectiveGeneration:
        """Resolve the independently configured default operation.

        Args:
            capability:
                Required operation.
            requested:
                Optional overrides.

        Returns:
            Immutable effective default selection.
        """

        ...

    def response_gateway(self, provider: str) -> ResponseGateway:
        """Select a response adapter.

        Args:
            provider:
                Provider key.

        Returns:
            Response capability implementation.
        """

        ...

    def summary_gateway(self, provider: str) -> SummaryGateway:
        """Select a summary adapter independently of responses.

        Args:
            provider:
                Provider key.

        Returns:
            Summary capability implementation.
        """

        ...

    def token_counter(self, provider: str) -> TokenCounter:
        """Select deterministic token accounting.

        Args:
            provider:
                Provider key.

        Returns:
            Provider token counter.
        """

        ...
