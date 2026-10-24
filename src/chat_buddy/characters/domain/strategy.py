"""Common identity for versioned Characters strategies."""

from pydantic import BaseModel, ConfigDict, Field


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
        pattern=r"^[a-z][a-z0-9_.-]*$",
        description="Stable machine-readable strategy name.",
    )
    version: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$",
        description="Semantic strategy behavior version.",
    )
