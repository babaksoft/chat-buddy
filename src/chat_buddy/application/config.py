from dataclasses import dataclass

from chat_buddy.infrastructure.config import settings


@dataclass(slots=True, frozen=True)
class ContextBuilderConfig:
    model_context_window: int = settings.MODEL_CONTEXT_WINDOW
    prompt_overhead_tokens: int = settings.PROMPT_OVERHEAD_TOKENS
    summary_trigger_ratio: float = settings.SUMMARY_TRIGGER_RATIO
