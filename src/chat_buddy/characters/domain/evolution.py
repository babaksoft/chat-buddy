"""Immutable values and contracts for continuity-scoped evolution."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chat_buddy.characters.domain.continuity import (
    Boundary,
    ContinuityMode,
    RelationshipIntent,
)
from chat_buddy.characters.domain.identity import Identity
from chat_buddy.characters.domain.persona import Persona
from chat_buddy.characters.domain.strategy import StrategyIdentity
from chat_buddy.characters.domain.validation import NON_BLANK_TEXT_PATTERN

MAX_EVOLUTION_COMMANDS = 8
MAX_COMMAND_SOURCES = 8


class AdaptationFacet(StrEnum):
    """Initial versioned vocabulary for continuity-local persona adaptation."""

    COMMUNICATION_STYLE = "communication_style"
    OPENNESS = "openness"
    SUPPORT_STYLE = "support_style"
    CONFLICT_STYLE = "conflict_style"
    SHARED_HABIT = "shared_habit"


class RelationshipSocialStatus(StrEnum):
    """Exact social values available to evolution."""

    STRANGER = "stranger"
    ACQUAINTANCE = "acquaintance"
    CASUAL_FRIEND = "casual_friend"
    CLOSE_FRIEND = "close_friend"


class RelationshipRomanticStatus(StrEnum):
    """Exact romantic values available to evolution."""

    NONE = "none"
    INTEREST = "interest"
    DATING = "dating"
    PARTNER = "partner"
    ENGAGED = "engaged"
    SPOUSE = "spouse"


class RelationshipDynamic(StrEnum):
    """Exact interaction dynamics available to evolution."""

    NEUTRAL = "neutral"
    COMFORTABLE = "comfortable"
    AWKWARD = "awkward"
    TENSE = "tense"
    ESTRANGED = "estranged"


class RelationshipTrust(StrEnum):
    """Exact trust values available to evolution."""

    UNKNOWN = "unknown"
    CAUTIOUS = "cautious"
    TRUSTING = "trusting"


class RelationshipAffection(StrEnum):
    """Exact affection values available to evolution."""

    NEUTRAL = "neutral"
    WARM = "warm"
    AFFECTIONATE = "affectionate"


class RelationshipMilestone(StrEnum):
    """Explicit narrative milestones retained independently of status."""

    PARTNERSHIP = "partnership"
    ENGAGEMENT = "engagement"
    MARRIAGE = "marriage"
    BREAKUP = "breakup"
    RECONCILIATION = "reconciliation"


class EvolutionEvidenceKind(StrEnum):
    """Supported exact evidence checkpoint shapes."""

    ONGOING_TURN = "ongoing_turn"
    STORYLINE_CHECKPOINT = "storyline_checkpoint"


class EvolutionDecisionOutcome(StrEnum):
    """Terminal application outcomes for one atomic proposal."""

    NO_CHANGE = "no_change"
    APPLIED = "applied"
    REJECTED = "rejected"


class EvolutionRejectionReason(StrEnum):
    """Stable categories used when an atomic proposal is rejected."""

    OWNERSHIP = "ownership"
    EVIDENCE = "evidence"
    EXPECTED_PROJECTION = "expected_projection"
    RELATIONSHIP_INTENT = "relationship_intent"
    USER_BOUNDARY = "user_boundary"
    TRANSITION = "transition"
    THRESHOLD = "threshold"
    PERSONA_CORE = "persona_core"
    ADAPTATION_FACET = "adaptation_facet"
    PROPOSAL_BOUNDS = "proposal_bounds"


class EvolutionScope(BaseModel):
    """Ownership shared by all evolution state in one continuity.

    Attributes:
        identity_id:
            Permanent identity owner.
        persona_id:
            Permanent persona owner.
        continuity_id:
            Permanent continuity owner.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity_id: UUID = Field(description="Permanent identity owner.")
    persona_id: UUID = Field(description="Permanent persona owner.")
    continuity_id: UUID = Field(description="Permanent continuity owner.")


class EvolutionEvidenceReference(BaseModel):
    """Exact selected-history turn or Storyline checkpoint reference.

    Attributes:
        scope:
            Continuity ownership of the evidence.
        kind:
            Ongoing turn or Storyline checkpoint shape.
        conversation_id:
            Exact source conversation, including one scene conversation.
        scene_id:
            Storyline scene owner, absent for Ongoing.
        scene_position:
            Storyline scene position, absent for Ongoing.
        user_message_id:
            Source user message identifier.
        user_sequence:
            Source user message position within its conversation.
        persona_message_id:
            Adjacent source persona message identifier.
        persona_sequence:
            Source persona checkpoint position within its conversation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: EvolutionScope = Field(description="Continuity evidence ownership.")
    kind: EvolutionEvidenceKind = Field(description="Evidence checkpoint shape.")
    conversation_id: UUID = Field(description="Exact source conversation.")
    scene_id: UUID | None = Field(
        default=None, description="Storyline scene owner when applicable."
    )
    scene_position: int | None = Field(
        default=None, ge=1, description="Storyline scene position when applicable."
    )
    user_message_id: UUID = Field(description="Source user message identifier.")
    user_sequence: int = Field(gt=0, description="Source user message position.")
    persona_message_id: UUID = Field(description="Source persona message identifier.")
    persona_sequence: int = Field(
        gt=0, description="Source persona checkpoint position."
    )

    @model_validator(mode="after")
    def validate_checkpoint_shape(self) -> Self:
        """Require adjacent messages and mode-specific scene ownership.

        Returns:
            Validated exact evidence reference.

        Raises:
            ValueError:
                If message positions or scene ownership are malformed.
        """

        if self.persona_sequence != self.user_sequence + 1:
            raise ValueError("Evolution evidence must reference one adjacent turn.")
        if self.kind == EvolutionEvidenceKind.ONGOING_TURN and (
            self.scene_id is not None or self.scene_position is not None
        ):
            raise ValueError("Ongoing evidence cannot reference a Storyline scene.")
        if self.kind == EvolutionEvidenceKind.STORYLINE_CHECKPOINT and (
            self.scene_id is None or self.scene_position is None
        ):
            raise ValueError("Storyline evidence requires a scene checkpoint.")
        return self


class EvolutionEvidence(BaseModel):
    """Exact immutable evidence text paired with its reference.

    Attributes:
        reference:
            Selected-history checkpoint provenance.
        user_content:
            Exact committed user content.
        persona_content:
            Exact committed persona response.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    reference: EvolutionEvidenceReference = Field(
        description="Selected-history checkpoint provenance."
    )
    user_content: str = Field(
        min_length=1,
        max_length=32768,
        pattern=NON_BLANK_TEXT_PATTERN,
        description="Exact committed user content.",
    )
    persona_content: str = Field(
        min_length=1,
        max_length=32768,
        pattern=NON_BLANK_TEXT_PATTERN,
        description="Exact committed persona content.",
    )


class RelationshipProjection(BaseModel):
    """Rebuildable current qualitative relationship view.

    Attributes:
        scope:
            Owning identity, persona, and continuity.
        revision:
            Replay revision, zero for the starting projection.
        social:
            Current social status.
        romantic:
            Current romantic status.
        dynamic:
            Current interaction dynamic.
        trust:
            Current trust state.
        affection:
            Current affection state.
        milestones:
            Unique explicit milestones in replay order.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: EvolutionScope = Field(description="Projection ownership.")
    revision: int = Field(ge=0, description="Replay revision.")
    social: RelationshipSocialStatus = Field(description="Current social status.")
    romantic: RelationshipRomanticStatus = Field(description="Current romantic status.")
    dynamic: RelationshipDynamic = Field(description="Current interaction dynamic.")
    trust: RelationshipTrust = Field(description="Current trust state.")
    affection: RelationshipAffection = Field(description="Current affection state.")
    milestones: tuple[RelationshipMilestone, ...] = Field(
        default=(), description="Explicit milestones in replay order."
    )

    @model_validator(mode="after")
    def validate_unique_milestones(self) -> Self:
        """Reject duplicate milestone state.

        Returns:
            Validated projection.

        Raises:
            ValueError:
                If a milestone appears more than once.
        """

        if len(set(self.milestones)) != len(self.milestones):
            raise ValueError("Relationship projection milestones must be unique.")
        return self


class PersonaAdaptation(BaseModel):
    """One active continuity-local behavioral specialization.

    Attributes:
        facet:
            Exact adaptation facet.
        value:
            Concise current behavioral specialization.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    facet: AdaptationFacet = Field(description="Exact adaptation facet.")
    value: str = Field(
        min_length=1,
        max_length=512,
        pattern=NON_BLANK_TEXT_PATTERN,
        description="Current behavioral specialization.",
    )


class PersonaAdaptationProjection(BaseModel):
    """Rebuildable active persona adaptations for one continuity.

    Attributes:
        scope:
            Owning identity, persona, and continuity.
        revision:
            Replay revision, zero for an empty starting projection.
        adaptations:
            Active adaptations with at most one value per facet.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: EvolutionScope = Field(description="Projection ownership.")
    revision: int = Field(ge=0, description="Replay revision.")
    adaptations: tuple[PersonaAdaptation, ...] = Field(
        default=(), description="Active adaptations."
    )

    @model_validator(mode="after")
    def validate_unique_facets(self) -> Self:
        """Require at most one active value for each facet.

        Returns:
            Validated projection.

        Raises:
            ValueError:
                If an adaptation facet is duplicated.
        """

        facets = tuple(item.facet for item in self.adaptations)
        if len(set(facets)) != len(facets):
            raise ValueError("Persona adaptation facets must be unique.")
        return self


class EvolutionSnapshot(BaseModel):
    """Immutable strategy input with continuity-safe evidence.

    Attributes:
        scope:
            Evolution ownership independent of a single conversation.
        mode:
            Continuity mode governing evidence shape.
        identity:
            Immutable authored identity snapshot.
        persona:
            Immutable authored persona-core snapshot.
        relationship_intent:
            User-selected relationship direction.
        boundaries:
            User-controlled restrictions.
        relationship:
            Current relationship projection.
        persona_adaptations:
            Current adaptation projection.
        evidence:
            Unique chronological exact evidence.
        source:
            New persona checkpoint whose effect is being evaluated.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: EvolutionScope = Field(description="Evolution ownership.")
    mode: ContinuityMode = Field(description="Continuity mode.")
    identity: Identity = Field(description="Immutable authored identity snapshot.")
    persona: Persona = Field(description="Immutable authored persona-core snapshot.")
    relationship_intent: RelationshipIntent = Field(
        description="User-selected relationship direction."
    )
    boundaries: tuple[Boundary, ...] = Field(
        description="User-controlled restrictions."
    )
    relationship: RelationshipProjection = Field(
        description="Current relationship projection."
    )
    persona_adaptations: PersonaAdaptationProjection = Field(
        description="Current persona-adaptation projection."
    )
    evidence: tuple[EvolutionEvidence, ...] = Field(
        min_length=1, description="Chronological exact evidence."
    )
    source: EvolutionEvidenceReference = Field(
        description="New source checkpoint being evaluated."
    )

    @model_validator(mode="after")
    def validate_ownership_and_evidence(self) -> Self:
        """Require one owner, valid mode shapes, and unique ordered evidence.

        Returns:
            Validated strategy snapshot.

        Raises:
            ValueError:
                If snapshots or evidence are foreign, duplicated, or reordered.
        """

        if self.identity.id != self.scope.identity_id:
            raise ValueError("Identity snapshot does not match the evolution scope.")
        if self.persona.id != self.scope.persona_id:
            raise ValueError("Persona snapshot does not match the evolution scope.")
        if self.relationship.scope != self.scope:
            raise ValueError("Relationship projection is foreign to the snapshot.")
        if self.persona_adaptations.scope != self.scope:
            raise ValueError("Adaptation projection is foreign to the snapshot.")
        if len(set(self.boundaries)) != len(self.boundaries):
            raise ValueError("Evolution snapshot boundaries must be unique.")

        references = tuple(item.reference for item in self.evidence)
        if len(set(references)) != len(references):
            raise ValueError("Evolution evidence references must be unique.")
        if any(reference.scope != self.scope for reference in references):
            raise ValueError("Evolution evidence is foreign to the snapshot.")
        expected_kind = (
            EvolutionEvidenceKind.ONGOING_TURN
            if self.mode == ContinuityMode.ONGOING
            else EvolutionEvidenceKind.STORYLINE_CHECKPOINT
        )
        if self.mode == ContinuityMode.TIMELINE or any(
            reference.kind != expected_kind for reference in references
        ):
            raise ValueError("Evolution evidence does not match the continuity mode.")
        if (
            self.mode == ContinuityMode.ONGOING
            and len({reference.conversation_id for reference in references}) != 1
        ):
            raise ValueError("Ongoing evidence must share its sole conversation.")
        positions = tuple(_evidence_position(reference) for reference in references)
        if positions != tuple(sorted(positions)):
            raise ValueError("Evolution evidence must be chronological.")
        if self.source != references[-1]:
            raise ValueError("Evolution source must be the latest exact evidence.")
        return self


class EvolutionProvenance(BaseModel):
    """Exact versioned configuration that produced and judged evolution.

    Attributes:
        selector:
            Evidence selector identity.
        strategy:
            Proposal strategy identity.
        policy:
            Threshold-policy identity.
        schema_identity:
            Typed proposal schema identity.
        provider:
            Optional external provider key.
        model:
            Optional external model identifier.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    selector: StrategyIdentity = Field(description="Evidence selector identity.")
    strategy: StrategyIdentity = Field(description="Proposal strategy identity.")
    policy: StrategyIdentity = Field(description="Threshold-policy identity.")
    schema_identity: StrategyIdentity = Field(description="Proposal schema identity.")
    provider: str | None = Field(
        default=None, min_length=1, max_length=64, description="Provider key."
    )
    model: str | None = Field(
        default=None, min_length=1, max_length=256, description="Model identifier."
    )

    @model_validator(mode="after")
    def validate_provider_pair(self) -> Self:
        """Require provider and model provenance together.

        Returns:
            Validated configuration provenance.

        Raises:
            ValueError:
                If only one external generation field is present.
        """

        if (self.provider is None) != (self.model is None):
            raise ValueError("Evolution provider and model must be recorded together.")
        return self


class _EvidenceBasedCommand(BaseModel):
    """Shared bounded evidence and rationale for one atomic command.

    Attributes:
        rationale:
            Concise explanation of the proposed interpretation.
        sources:
            Unique exact evidence supporting the command.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    rationale: str = Field(
        min_length=1,
        max_length=1024,
        pattern=NON_BLANK_TEXT_PATTERN,
        description="Concise proposal rationale.",
    )
    sources: tuple[EvolutionEvidenceReference, ...] = Field(
        min_length=1,
        max_length=MAX_COMMAND_SOURCES,
        description="Unique exact supporting evidence.",
    )

    @model_validator(mode="after")
    def validate_unique_sources(self) -> Self:
        """Reject repeated source citations.

        Returns:
            Validated evidence-based command.

        Raises:
            ValueError:
                If a source reference is duplicated.
        """

        if len(set(self.sources)) != len(self.sources):
            raise ValueError("Evolution command sources must be unique.")
        return self


class SetSocialStatusCommand(_EvidenceBasedCommand):
    """Replace the social status from an expected value.

    Attributes:
        kind:
            Stable command discriminator.
        expected:
            Required current social status.
        value:
            Proposed replacement social status.
    """

    kind: Literal["set_social_status"] = "set_social_status"
    expected: RelationshipSocialStatus = Field(
        description="Required current social status."
    )
    value: RelationshipSocialStatus = Field(description="Proposed social status.")

    @model_validator(mode="after")
    def validate_change(self) -> Self:
        """Reject a no-op social transition.

        Returns:
            Validated command.

        Raises:
            ValueError:
                If current and proposed states are identical.
        """

        return _require_change(self, self.expected, self.value)


class SetRomanticStatusCommand(_EvidenceBasedCommand):
    """Replace the romantic status from an expected value.

    Attributes:
        kind:
            Stable command discriminator.
        expected:
            Required current romantic status.
        value:
            Proposed replacement romantic status.
    """

    kind: Literal["set_romantic_status"] = "set_romantic_status"
    expected: RelationshipRomanticStatus = Field(
        description="Required current romantic status."
    )
    value: RelationshipRomanticStatus = Field(description="Proposed romantic status.")

    @model_validator(mode="after")
    def validate_change(self) -> Self:
        """Reject a no-op romantic transition.

        Returns:
            Validated command.

        Raises:
            ValueError:
                If current and proposed states are identical.
        """

        return _require_change(self, self.expected, self.value)


class SetDynamicCommand(_EvidenceBasedCommand):
    """Replace the current interaction dynamic.

    Attributes:
        kind:
            Stable command discriminator.
        expected:
            Required current dynamic.
        value:
            Proposed replacement dynamic.
    """

    kind: Literal["set_dynamic"] = "set_dynamic"
    expected: RelationshipDynamic = Field(description="Required current dynamic.")
    value: RelationshipDynamic = Field(description="Proposed interaction dynamic.")

    @model_validator(mode="after")
    def validate_change(self) -> Self:
        """Reject a no-op dynamic transition.

        Returns:
            Validated command.

        Raises:
            ValueError:
                If current and proposed states are identical.
        """

        return _require_change(self, self.expected, self.value)


class SetTrustCommand(_EvidenceBasedCommand):
    """Replace the trust state from an expected value.

    Attributes:
        kind:
            Stable command discriminator.
        expected:
            Required current trust state.
        value:
            Proposed replacement trust state.
    """

    kind: Literal["set_trust"] = "set_trust"
    expected: RelationshipTrust = Field(description="Required current trust state.")
    value: RelationshipTrust = Field(description="Proposed trust state.")

    @model_validator(mode="after")
    def validate_change(self) -> Self:
        """Reject a no-op trust transition.

        Returns:
            Validated command.

        Raises:
            ValueError:
                If current and proposed states are identical.
        """

        return _require_change(self, self.expected, self.value)


class SetAffectionCommand(_EvidenceBasedCommand):
    """Replace the affection state from an expected value.

    Attributes:
        kind:
            Stable command discriminator.
        expected:
            Required current affection state.
        value:
            Proposed replacement affection state.
    """

    kind: Literal["set_affection"] = "set_affection"
    expected: RelationshipAffection = Field(
        description="Required current affection state."
    )
    value: RelationshipAffection = Field(description="Proposed affection state.")

    @model_validator(mode="after")
    def validate_change(self) -> Self:
        """Reject a no-op affection transition.

        Returns:
            Validated command.

        Raises:
            ValueError:
                If current and proposed states are identical.
        """

        return _require_change(self, self.expected, self.value)


class RecordRelationshipMilestoneCommand(_EvidenceBasedCommand):
    """Record an explicit milestone and its coherent romantic transition.

    Attributes:
        kind:
            Stable command discriminator.
        milestone:
            Explicit narrative milestone.
        expected:
            Required current romantic status.
        value:
            Romantic status resulting from the milestone.
    """

    kind: Literal["record_relationship_milestone"] = "record_relationship_milestone"
    milestone: RelationshipMilestone = Field(description="Explicit milestone.")
    expected: RelationshipRomanticStatus = Field(
        description="Required current romantic status."
    )
    value: RelationshipRomanticStatus = Field(description="Resulting romantic status.")

    @model_validator(mode="after")
    def validate_milestone_shape(self) -> Self:
        """Reject no-op or milestone/status contradictions.

        Returns:
            Validated milestone command.

        Raises:
            ValueError:
                If the transition cannot represent the named milestone.
        """

        _require_change(self, self.expected, self.value)
        required = {
            RelationshipMilestone.PARTNERSHIP: RelationshipRomanticStatus.PARTNER,
            RelationshipMilestone.ENGAGEMENT: RelationshipRomanticStatus.ENGAGED,
            RelationshipMilestone.MARRIAGE: RelationshipRomanticStatus.SPOUSE,
            RelationshipMilestone.BREAKUP: RelationshipRomanticStatus.NONE,
        }
        if self.milestone in required and self.value != required[self.milestone]:
            raise ValueError("Relationship milestone has an invalid resulting status.")
        if (
            self.milestone == RelationshipMilestone.RECONCILIATION
            and self.value == RelationshipRomanticStatus.NONE
        ):
            raise ValueError("Reconciliation requires a restored romantic status.")
        return self


class SetPersonaAdaptationCommand(_EvidenceBasedCommand):
    """Set or replace one typed persona-adaptation facet.

    Attributes:
        kind:
            Stable command discriminator.
        facet:
            Exact adaptation facet.
        expected:
            Current value, or None when adding the facet.
        value:
            Proposed concise behavioral specialization.
    """

    kind: Literal["set_persona_adaptation"] = "set_persona_adaptation"
    facet: AdaptationFacet = Field(description="Exact adaptation facet.")
    expected: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        pattern=NON_BLANK_TEXT_PATTERN,
        description="Required current value when replacing a facet.",
    )
    value: str = Field(
        min_length=1,
        max_length=512,
        pattern=NON_BLANK_TEXT_PATTERN,
        description="Proposed behavioral specialization.",
    )

    @model_validator(mode="after")
    def validate_change(self) -> Self:
        """Reject replacing an adaptation with the same value.

        Returns:
            Validated command.

        Raises:
            ValueError:
                If current and proposed values are identical.
        """

        if self.expected == self.value:
            raise ValueError("Evolution commands must change their target value.")
        return self


class RemovePersonaAdaptationCommand(_EvidenceBasedCommand):
    """Remove one expected active persona-adaptation facet.

    Attributes:
        kind:
            Stable command discriminator.
        facet:
            Exact adaptation facet.
        expected:
            Required current adaptation value.
    """

    kind: Literal["remove_persona_adaptation"] = "remove_persona_adaptation"
    facet: AdaptationFacet = Field(description="Exact adaptation facet.")
    expected: str = Field(
        min_length=1,
        max_length=512,
        pattern=NON_BLANK_TEXT_PATTERN,
        description="Required current adaptation value.",
    )


type EvolutionCommand = Annotated[
    SetSocialStatusCommand
    | SetRomanticStatusCommand
    | SetDynamicCommand
    | SetTrustCommand
    | SetAffectionCommand
    | RecordRelationshipMilestoneCommand
    | SetPersonaAdaptationCommand
    | RemovePersonaAdaptationCommand,
    Field(discriminator="kind"),
]


class EvolutionProposal(BaseModel):
    """Bounded atomic strategy output without durable-state authority.

    Attributes:
        id:
            Stable proposal identifier.
        scope:
            Continuity ownership copied from the snapshot.
        expected_relationship_revision:
            Relationship projection revision evaluated by the strategy.
        expected_adaptation_revision:
            Adaptation projection revision evaluated by the strategy.
        source:
            New source checkpoint being interpreted.
        provenance:
            Exact versioned experimental configuration.
        commands:
            Bounded typed changes applied or rejected together.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(description="Stable proposal identifier.")
    scope: EvolutionScope = Field(description="Continuity ownership.")
    expected_relationship_revision: int = Field(
        ge=0, description="Expected relationship projection revision."
    )
    expected_adaptation_revision: int = Field(
        ge=0, description="Expected adaptation projection revision."
    )
    source: EvolutionEvidenceReference = Field(
        description="New source checkpoint being interpreted."
    )
    provenance: EvolutionProvenance = Field(
        description="Exact versioned experimental configuration."
    )
    commands: tuple[EvolutionCommand, ...] = Field(
        default=(),
        max_length=MAX_EVOLUTION_COMMANDS,
        description="Bounded atomic typed changes.",
    )

    @model_validator(mode="after")
    def validate_atomic_shape(self) -> Self:
        """Require one owner and at most one command for each target.

        Returns:
            Validated atomic proposal.

        Raises:
            ValueError:
                If evidence is foreign or command targets conflict.
        """

        if self.source.scope != self.scope:
            raise ValueError("Evolution proposal source is foreign.")
        if any(
            source.scope != self.scope
            for command in self.commands
            for source in command.sources
        ):
            raise ValueError("Evolution proposal evidence is foreign.")
        targets = tuple(_command_target(command) for command in self.commands)
        if len(set(targets)) != len(targets):
            raise ValueError("Evolution proposal command targets must be unique.")
        return self


class EvolutionEvent(BaseModel):
    """One immutable accepted change used to rebuild projections.

    Attributes:
        id:
            Stable event identifier.
        proposal_id:
            Accepted atomic proposal identifier.
        scope:
            Continuity ownership.
        command:
            Accepted typed change.
        relationship_revision:
            Relationship revision after this event.
        adaptation_revision:
            Adaptation revision after this event.
        provenance:
            Exact strategy and policy provenance.
        created_at:
            Event creation timestamp.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(description="Stable event identifier.")
    proposal_id: UUID = Field(description="Accepted proposal identifier.")
    scope: EvolutionScope = Field(description="Continuity ownership.")
    command: EvolutionCommand = Field(description="Accepted typed change.")
    relationship_revision: int = Field(
        ge=0, description="Relationship revision after this event."
    )
    adaptation_revision: int = Field(
        ge=0, description="Adaptation revision after this event."
    )
    provenance: EvolutionProvenance = Field(
        description="Exact strategy and policy provenance."
    )
    created_at: datetime = Field(description="Event creation timestamp.")

    @model_validator(mode="after")
    def validate_ownership(self) -> Self:
        """Reject accepted commands citing foreign evidence.

        Returns:
            Validated immutable event.

        Raises:
            ValueError:
                If command evidence belongs to another continuity.
        """

        if any(source.scope != self.scope for source in self.command.sources):
            raise ValueError("Evolution event evidence is foreign.")
        return self


class EvolutionDecision(BaseModel):
    """Terminal application result for one atomic proposal.

    Attributes:
        proposal_id:
            Evaluated proposal identifier.
        outcome:
            No-change, applied, or rejected result.
        reason:
            Stable rejection category when rejected.
        events:
            Accepted events, present only for an applied proposal.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: UUID = Field(description="Evaluated proposal identifier.")
    outcome: EvolutionDecisionOutcome = Field(description="Terminal outcome.")
    reason: EvolutionRejectionReason | None = Field(
        default=None, description="Stable rejection category."
    )
    events: tuple[EvolutionEvent, ...] = Field(
        default=(),
        max_length=MAX_EVOLUTION_COMMANDS,
        description="Accepted events for an applied proposal.",
    )

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        """Require outcome-consistent reason and event data.

        Returns:
            Validated terminal decision.

        Raises:
            ValueError:
                If rejection or event data contradicts the outcome.
        """

        if self.outcome == EvolutionDecisionOutcome.REJECTED:
            if self.reason is None or self.events:
                raise ValueError("Rejected evolution requires only a reason.")
        elif self.reason is not None:
            raise ValueError("Only rejected evolution may carry a reason.")
        elif self.outcome == EvolutionDecisionOutcome.APPLIED and not self.events:
            raise ValueError("Applied evolution requires accepted events.")
        elif self.outcome == EvolutionDecisionOutcome.NO_CHANGE and self.events:
            raise ValueError("No-change evolution cannot carry events.")
        if any(event.proposal_id != self.proposal_id for event in self.events):
            raise ValueError("Evolution decision contains a foreign event.")
        return self


class EvolutionStrategy(Protocol):
    """Replaceable typed proposal strategy."""

    @property
    def strategy_id(self) -> StrategyIdentity:
        """Return the stable name and behavior version.

        Returns:
            Strategy identity recorded in proposal provenance.
        """

        ...

    def propose(self, snapshot: EvolutionSnapshot) -> EvolutionProposal:
        """Generate a detached proposal from one immutable snapshot.

        Args:
            snapshot:
                Validated state and exact eligible evidence.

        Returns:
            Bounded typed proposal carrying exact provenance.
        """

        ...


def _evidence_position(reference: EvolutionEvidenceReference) -> tuple[int, int]:
    """Return a comparable chronological position.

    Args:
        reference:
            Exact evidence reference.

    Returns:
        Scene and message position pair.
    """

    return (reference.scene_position or 0, reference.persona_sequence)


def _require_change[CommandT](
    command: CommandT, expected: object, value: object
) -> CommandT:
    """Require a command to replace its target value.

    Args:
        command:
            Command returned unchanged when valid.
        expected:
            Required current value.
        value:
            Proposed replacement value.

    Returns:
        The validated command.

    Raises:
        ValueError:
            If the command is a no-op.
    """

    if expected == value:
        raise ValueError("Evolution commands must change their target value.")
    return command


def _command_target(command: EvolutionCommand) -> str:
    """Return the atomic projection target for a command.

    Args:
        command:
            Typed evolution command.

    Returns:
        Stable relationship dimension or adaptation facet target.
    """

    if isinstance(
        command, (SetPersonaAdaptationCommand, RemovePersonaAdaptationCommand)
    ):
        return f"adaptation:{command.facet}"
    if isinstance(
        command, (SetRomanticStatusCommand, RecordRelationshipMilestoneCommand)
    ):
        return "relationship:romantic"
    return f"relationship:{command.kind.removeprefix('set_')}"
