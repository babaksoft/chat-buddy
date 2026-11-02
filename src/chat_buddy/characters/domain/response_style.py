"""Immutable response-presentation settings and snapshots."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from chat_buddy.characters.domain.validation import (
    MACHINE_READABLE_NAME_PATTERN,
    NON_BLANK_TEXT_PATTERN,
    SEMANTIC_VERSION_PATTERN,
)


class SceneDescriptionLevel(StrEnum):
    """Allowed amounts of environmental, action, and non-verbal description."""

    NONE = "none"
    LIGHT = "light"
    BALANCED = "balanced"
    RICH = "rich"


class ResponseLength(StrEnum):
    """Allowed target response extents."""

    CONCISE = "concise"
    BALANCED = "balanced"
    EXPANSIVE = "expansive"


class NarrativePlacement(StrEnum):
    """Allowed placement of scene description relative to ordinary prose."""

    BEFORE_DIALOGUE = "before_dialogue"
    INTERLEAVED = "interleaved"
    AFTER_DIALOGUE = "after_dialogue"


class ResponseStyleSettings(BaseModel):
    """Validated requested response-presentation controls.

    Attributes:
        scene_description:
            Requested scene-description amount.
        response_length:
            Requested target response extent.
        narrative_placement:
            Requested placement of scene description.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scene_description: SceneDescriptionLevel = Field(
        description="Requested scene-description amount."
    )
    response_length: ResponseLength = Field(
        description="Requested target response extent."
    )
    narrative_placement: NarrativePlacement = Field(
        description="Requested placement of scene description."
    )


class VersionedResponseStyleSettings(BaseModel):
    """Current continuity-owned settings under an optimistic revision.

    Attributes:
        settings:
            Complete current requested settings.
        revision:
            Positive optimistic style revision.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    settings: ResponseStyleSettings = Field(description="Current requested settings.")
    revision: int = Field(
        ge=1, strict=True, description="Positive optimistic style revision."
    )


class StyleUpdateStatus(StrEnum):
    """Explicit outcomes of a guarded continuity style update."""

    UPDATED = "updated"
    IDEMPOTENT = "idempotent"
    STALE_REVISION = "stale_revision"
    ARCHIVED = "archived"


class StyleUpdateResult(BaseModel):
    """Result of replacing continuity-owned style under a revision guard.

    Attributes:
        status:
            Stable update outcome.
        style:
            Current committed style for every outcome.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: StyleUpdateStatus = Field(description="Stable update outcome.")
    style: VersionedResponseStyleSettings = Field(
        description="Current committed style settings."
    )


class ResponseStyle(BaseModel):
    """Exact effective response presentation copied to an attempt and message.

    Attributes:
        name:
            Stable machine-readable renderer name.
        version:
            Semantic renderer behavior version.
        scene_description:
            Resolved scene-description amount.
        response_length:
            Resolved target response extent.
        narrative_placement:
            Resolved placement of scene description.
        source_revision:
            Style revision read when the attempt was reserved.
        instruction:
            Exact deterministic non-secret instruction effective for the response.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=128,
        pattern=MACHINE_READABLE_NAME_PATTERN,
        description="Stable machine-readable renderer name.",
    )
    version: str = Field(
        min_length=1,
        max_length=64,
        pattern=SEMANTIC_VERSION_PATTERN,
        description="Semantic renderer behavior version.",
    )
    scene_description: SceneDescriptionLevel = Field(
        default=SceneDescriptionLevel.BALANCED,
        description="Resolved scene-description amount.",
    )
    response_length: ResponseLength = Field(
        default=ResponseLength.BALANCED,
        description="Resolved target response extent.",
    )
    narrative_placement: NarrativePlacement = Field(
        default=NarrativePlacement.INTERLEAVED,
        description="Resolved placement of scene description.",
    )
    source_revision: int = Field(
        default=1,
        ge=1,
        strict=True,
        description="Style revision read at attempt reservation.",
    )
    instruction: str = Field(
        min_length=1,
        max_length=4096,
        pattern=NON_BLANK_TEXT_PATTERN,
        description="Exact deterministic response-presentation instruction.",
    )
