"""Replaceable, non-persistent evolution strategy values and contracts."""

from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chat_buddy.characters.domain.continuity import ContinuityMode, StartingRelationship
from chat_buddy.characters.domain.conversation import ConversationScope
from chat_buddy.characters.domain.identity import Identity
from chat_buddy.characters.domain.persona import Persona
from chat_buddy.characters.domain.summary import CompletedTurn


class EvolutionStrategyId(BaseModel):
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


class EvolutionEvidenceReference(BaseModel):
    """Reference to one eligible complete conversation turn.

    Attributes:
        user_message_id:
            Source user message identifier.
        persona_message_id:
            Adjacent source persona message identifier.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_message_id: UUID = Field(description="Source user message identifier.")
    persona_message_id: UUID = Field(description="Source persona message identifier.")


class EvolutionInputs(BaseModel):
    """Immutable continuity-scoped snapshots and eligible evidence.

    Attributes:
        scope:
            Complete identity, persona, continuity, and conversation references.
        mode:
            Mode governing evidence eligibility.
        identity:
            Authored identity snapshot supplied to the strategy.
        persona:
            Authored persona-core snapshot supplied to the strategy.
        starting_relationship:
            Continuity-owned starting relationship snapshot.
        evidence:
            Chronological eligible complete turns.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ConversationScope = Field(description="Complete ownership references.")
    mode: ContinuityMode = Field(description="Continuity mode.")
    identity: Identity = Field(description="Immutable authored identity snapshot.")
    persona: Persona = Field(description="Immutable authored persona-core snapshot.")
    starting_relationship: StartingRelationship = Field(
        description="Immutable continuity starting relationship snapshot."
    )
    evidence: tuple[CompletedTurn, ...] = Field(
        description="Chronological eligible complete turns."
    )

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        """Require every snapshot and evidence turn to share one scope.

        Returns:
            Validated scoped inputs.

        Raises:
            ValueError:
                If a profile or evidence turn belongs to another scope.
        """

        if self.identity.id != self.scope.identity_id:
            raise ValueError("Identity snapshot does not match the evolution scope.")
        if self.persona.id != self.scope.persona_id:
            raise ValueError("Persona snapshot does not match the evolution scope.")
        if any(turn.user.scope != self.scope for turn in self.evidence):
            raise ValueError("Evolution evidence must belong to the supplied scope.")

        sequences = tuple(turn.user.sequence for turn in self.evidence)
        if sequences != tuple(sorted(sequences)) or len(set(sequences)) != len(
            sequences
        ):
            raise ValueError("Evolution evidence must be unique and chronological.")

        return self


class PersonaAdaptationProposal(BaseModel):
    """Proposed continuity-local persona adaptation.

    Attributes:
        facet:
            Named adaptation facet affected by the proposal.
        proposed_value:
            Qualitative value proposed for that facet.
        rationale:
            Explanation for the proposed adaptation.
        sources:
            Eligible complete turns supporting the proposal.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    facet: str = Field(
        min_length=1, max_length=128, description="Named adaptation facet."
    )
    proposed_value: str = Field(
        min_length=1, max_length=4096, description="Proposed qualitative value."
    )
    rationale: str = Field(
        min_length=1, max_length=4096, description="Proposal rationale."
    )
    sources: tuple[EvolutionEvidenceReference, ...] = Field(
        min_length=1, description="Supporting eligible turn references."
    )


class RelationshipChangeProposal(BaseModel):
    """Proposed relationship-state change.

    Attributes:
        dimension:
            Starting-state dimension targeted by the proposal.
        proposed_value:
            Qualitative replacement proposed for the dimension.
        rationale:
            Explanation for the proposed change.
        sources:
            Eligible complete turns supporting the proposal.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    dimension: Literal[
        "social", "romantic", "dynamic", "trust", "affection", "boundaries"
    ] = Field(description="Relationship dimension targeted by the proposal.")
    proposed_value: str = Field(
        min_length=1, max_length=256, description="Proposed qualitative value."
    )
    rationale: str = Field(
        min_length=1, max_length=4096, description="Proposal rationale."
    )
    sources: tuple[EvolutionEvidenceReference, ...] = Field(
        min_length=1, description="Supporting eligible turn references."
    )


class EvolutionProposal(BaseModel):
    """Detached structured output that has no durable-state authority.

    Attributes:
        strategy:
            Exact strategy name and version that generated the result.
        scope:
            Ownership references copied from the evaluated input.
        persona_adaptations:
            Proposed continuity-local persona adaptations.
        relationship_changes:
            Proposed relationship-state changes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: EvolutionStrategyId = Field(description="Generating strategy identity.")
    scope: ConversationScope = Field(description="Evaluated ownership references.")
    persona_adaptations: tuple[PersonaAdaptationProposal, ...] = Field(
        default=(), description="Proposed persona adaptations."
    )
    relationship_changes: tuple[RelationshipChangeProposal, ...] = Field(
        default=(), description="Proposed relationship changes."
    )


class EvolutionStrategy(Protocol):
    """Replaceable proposal strategy."""

    @property
    def strategy_id(self) -> EvolutionStrategyId:
        """Return the stable name and behavior version.

        Returns:
            Strategy identity recorded on generated proposals.
        """

        ...

    def propose(self, inputs: EvolutionInputs) -> EvolutionProposal:
        """Generate a detached proposal from immutable scoped inputs.

        Args:
            inputs:
                Validated snapshots and eligible conversation evidence.

        Returns:
            Structured proposal carrying this strategy's identity.
        """

        ...
