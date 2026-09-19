from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ContextBuilderConfig:
    """Configuration required to build model context."""

    prompt_overhead_tokens: int
    summary_trigger_ratio: float
