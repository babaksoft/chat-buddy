"""Common identity for versioned Characters strategies."""

from pydantic import BaseModel, ConfigDict, Field

from chat_buddy.characters.domain.validation import (
    MACHINE_READABLE_NAME_PATTERN,
    SEMANTIC_VERSION_PATTERN,
)


class StrategyIdentity(BaseModel):
    """Stable identity recorded on every strategy result.

    Attributes:
        name:
            Stable machine-readable strategy name.
        version:
            Semantic version of the strategy behavior.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=128,
        pattern=MACHINE_READABLE_NAME_PATTERN,
        description="Stable machine-readable strategy name.",
    )
    version: str = Field(
        min_length=1,
        max_length=64,
        pattern=SEMANTIC_VERSION_PATTERN,
        description="Semantic strategy behavior version.",
    )
