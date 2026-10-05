"""Immutable continuity ownership and reviewed relationship starting values."""

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContinuityMode(StrEnum):
    """Modes with only Ongoing creation currently available."""

    ONGOING = "ongoing"
    STORYLINE = "storyline"
    TIMELINE = "timeline"


class ContinuityLifecycle(StrEnum):
    """Permanent writable or archived lifecycle."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class RelationshipIntent(StrEnum):
    """User-authored relationship direction."""

    PLATONIC = "platonic"
    OPEN_TO_ROMANCE = "open_to_romance"
    ESTABLISHED = "established_relationship"
    NATURAL = "let_it_develop_naturally"


SocialStatus = Literal["stranger", "acquaintance", "casual_friend", "close_friend"]
RomanticStatus = Literal["none", "interest", "dating", "partner", "engaged", "spouse"]
Dynamic = Literal["neutral", "comfortable", "awkward", "tense", "estranged"]
Trust = Literal["unknown", "cautious", "trusting"]
Affection = Literal["neutral", "warm", "affectionate"]
Boundary = Literal["no_romance", "no_flirting", "no_physical_intimacy"]
Origin = Literal["default", "user_selected"]


class RelationshipSelection(BaseModel):
    """Reviewed inputs with omission distinct from explicit default selections.

    Attributes:
        intent:
            Required relationship direction.
        social:
            Optional selected social status.
        romantic:
            Optional selected romantic status.
        dynamic:
            Optional selected current dynamic.
        trust:
            Optional selected trust.
        affection:
            Optional selected affection.
        boundaries:
            Optional unique selected boundaries.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: RelationshipIntent = Field(description="Reviewed relationship direction.")
    social: SocialStatus | None = Field(
        default=None, description="Selected social status."
    )
    romantic: RomanticStatus | None = Field(
        default=None, description="Selected romantic status."
    )
    dynamic: Dynamic | None = Field(
        default=None, description="Selected current dynamic."
    )
    trust: Trust | None = Field(default=None, description="Selected trust.")
    affection: Affection | None = Field(default=None, description="Selected affection.")
    boundaries: tuple[Boundary, ...] | None = Field(
        default=None, description="Selected boundaries."
    )

    @model_validator(mode="after")
    def validate_compatibility(self) -> Self:
        """Reject ambiguous established starts and conflicting restrictions.

        Returns:
            The validated immutable selection.

        Raises:
            ValueError:
                If selected statuses or boundaries conflict.
        """

        romantic = self.romantic or "none"
        boundaries = self.boundaries or ()
        if self.intent == RelationshipIntent.ESTABLISHED and (
            self.social is None
            or romantic not in {"dating", "partner", "engaged", "spouse"}
        ):
            raise ValueError(
                "Established starts require explicit social and established romantic statuses"
            )
        if self.intent == RelationshipIntent.PLATONIC and romantic != "none":
            raise ValueError("Platonic intent requires no romantic status")
        if len(set(boundaries)) != len(boundaries):
            raise ValueError("Boundaries must be unique")
        if "no_romance" in boundaries and romantic != "none":
            raise ValueError("No-romance boundary requires no romantic status")
        if "no_flirting" in boundaries and romantic == "interest":
            raise ValueError("No-flirting boundary conflicts with romantic interest")
        return self


class StartingOrigins(BaseModel):
    """Immutable provenance for every starting field.

    Attributes:
        social:
            Social selection origin.
        romantic:
            Romantic selection origin.
        dynamic:
            Dynamic selection origin.
        trust:
            Trust selection origin.
        affection:
            Affection selection origin.
        boundaries:
            Boundary selection origin.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    social: Origin = Field(description="Social origin.")
    romantic: Origin = Field(description="Romantic origin.")
    dynamic: Origin = Field(description="Dynamic origin.")
    trust: Origin = Field(description="Trust origin.")
    affection: Origin = Field(description="Affection origin.")
    boundaries: Origin = Field(description="Boundary origin.")


class StartingRelationship(BaseModel):
    """Continuity-owned qualitative snapshot without synthetic milestones.

    Attributes:
        intent:
            User-selected direction.
        social:
            Initial social status.
        romantic:
            Initial romantic status.
        dynamic:
            Initial current dynamic.
        trust:
            Initial trust.
        affection:
            Initial affection.
        boundaries:
            Initial restrictions.
        origins:
            Per-field selection provenance.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: RelationshipIntent = Field(description="User-selected direction.")
    social: SocialStatus = Field(description="Initial social status.")
    romantic: RomanticStatus = Field(description="Initial romantic status.")
    dynamic: Dynamic = Field(description="Initial current dynamic.")
    trust: Trust = Field(description="Initial trust.")
    affection: Affection = Field(description="Initial affection.")
    boundaries: tuple[Boundary, ...] = Field(description="Initial restrictions.")
    origins: StartingOrigins = Field(description="Per-field provenance.")


class StartContinuity(BaseModel):
    """Complete confirmed request retained for idempotent submission.

    Attributes:
        request_id:
            Unique confirmation identifier.
        identity_id:
            Reviewed identity.
        persona_id:
            Reviewed persona.
        identity_revision:
            Reviewed identity revision.
        persona_revision:
            Reviewed persona revision.
        mode:
            Requested continuity mode.
        relationship:
            Reviewed starting relationship inputs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: UUID = Field(description="Confirmation identifier.")
    identity_id: UUID = Field(description="Reviewed identity identifier.")
    persona_id: UUID = Field(description="Reviewed persona identifier.")
    identity_revision: int = Field(ge=1, description="Reviewed identity revision.")
    persona_revision: int = Field(ge=1, description="Reviewed persona revision.")
    mode: ContinuityMode = Field(
        default=ContinuityMode.ONGOING, description="Requested mode."
    )
    relationship: RelationshipSelection = Field(
        description="Reviewed relationship inputs."
    )


class Continuity(BaseModel):
    """Detached lifecycle snapshot with immutable ownership.

    Attributes:
        id:
            Stable continuity identifier.
        identity_id:
            Permanent identity owner.
        persona_id:
            Permanent persona owner.
        mode:
            Permanent mode binding.
        lifecycle:
            Current writable or archived state.
        conversation_id:
            Sole Ongoing conversation identifier.
        relationship:
            Independent starting relationship snapshot.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(description="Stable continuity identifier.")
    identity_id: UUID = Field(description="Permanent identity owner.")
    persona_id: UUID = Field(description="Permanent persona owner.")
    mode: ContinuityMode = Field(description="Permanent mode.")
    lifecycle: ContinuityLifecycle = Field(description="Current lifecycle.")
    conversation_id: UUID = Field(description="Sole conversation identifier.")
    relationship: StartingRelationship = Field(
        description="Independent starting snapshot."
    )


class ContinuityGroup(BaseModel):
    """Ordered navigation group for one identity/persona pair.

    Attributes:
        identity_id:
            Group identity owner.
        persona_id:
            Group persona owner.
        continuities:
            Active and archived snapshots ordered by identifier.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity_id: UUID = Field(description="Group identity owner.")
    persona_id: UUID = Field(description="Group persona owner.")
    continuities: tuple[Continuity, ...] = Field(
        description="Ordered lifecycle snapshots."
    )


class StartAvailability(BaseModel):
    """Whether an identity/persona pair may start a new Ongoing.

    Attributes:
        can_start:
            Whether the pair currently permits a new Ongoing.
        reason:
            Concise explanation when starting is unavailable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    can_start: bool = Field(description="Whether a new Ongoing may be started.")
    reason: str | None = Field(
        default=None,
        description="Explanation when a new Ongoing cannot be started.",
    )
