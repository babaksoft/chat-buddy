"""Immutable global authored persona cores owned by Characters."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PersonaCore(BaseModel):
    """Validated authored content shared across a persona's continuities.

    Attributes:
        name:
            Required display name.
        definition:
            Required authored character definition.
        traits:
            Optional free-form authored long-term traits.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    name: str = Field(
        min_length=1, max_length=128, description="Authored display name."
    )
    definition: str = Field(
        min_length=1, max_length=8192, description="Authored character definition."
    )
    traits: str | None = Field(
        default=None,
        min_length=1,
        max_length=4096,
        description="Optional authored long-term traits.",
    )


class Persona(BaseModel):
    """Immutable snapshot of a reusable persona and its edit eligibility.

    Attributes:
        id:
            Stable identifier preserved across authored replacements.
        core:
            Validated immutable authored core.
        revision:
            Positive authored revision for stale edit and start detection.
        is_frozen:
            Permanent global freeze after first continuity use with any identity.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(description="Stable persona identifier.")
    core: PersonaCore = Field(description="Immutable global authored core.")
    revision: int = Field(
        default=1, ge=1, description="Positive authored edit revision."
    )
    is_frozen: bool = Field(
        default=False, description="Permanent global freeze after first continuity use."
    )
