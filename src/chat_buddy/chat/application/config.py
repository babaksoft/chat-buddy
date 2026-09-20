from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ContextBuilderConfig:
    """Configuration required to build model context."""

    prompt_overhead_tokens: int
    summary_trigger_ratio: float


@dataclass(slots=True, frozen=True)
class RollingSummaryConfig:
    """Configuration for durable rolling-summary decisions."""

    prompt_overhead_tokens: int
    summary_trigger_ratio: float
    minimum_recent_turns: int = 2

    def __post_init__(self) -> None:
        """Validate token-budget and retention tuning values.

        Raises:
            ValueError:
                If a tuning value cannot define a valid summary policy.
        """

        if self.prompt_overhead_tokens < 0:
            raise ValueError("Prompt overhead must not be negative.")
        if not 0 < self.summary_trigger_ratio <= 1:
            raise ValueError(
                "Summary trigger ratio must be greater than 0 and at most 1."
            )
        if self.minimum_recent_turns < 1:
            raise ValueError("At least one recent turn must remain uncovered.")
