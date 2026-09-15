from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ContextBuilderConfig:
    """Configuration required to build model context."""

    model_context_window: int
    prompt_overhead_tokens: int
    summary_trigger_ratio: float


@dataclass(slots=True, frozen=True)
class MemoryConfig:
    """Configuration required by persistent memory services."""

    extraction_interval: int
