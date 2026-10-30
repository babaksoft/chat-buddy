"""Validated dataset and result values for native evolution evaluations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Protocol, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chat_buddy.characters.domain import (
    AdaptationFacet,
    Boundary,
    ContinuityMode,
    EvolutionDecision,
    EvolutionDecisionOutcome,
    EvolutionEvidence,
    EvolutionEvidenceKind,
    EvolutionEvidenceReference,
    EvolutionProposal,
    EvolutionRejectionReason,
    EvolutionScope,
    EvolutionSnapshot,
    Identity,
    IdentityDetails,
    Persona,
    PersonaAdaptation,
    PersonaAdaptationProjection,
    PersonaCore,
    RelationshipAffection,
    RelationshipDynamic,
    RelationshipIntent,
    RelationshipMilestone,
    RelationshipProjection,
    RelationshipRomanticStatus,
    RelationshipSocialStatus,
    RelationshipTrust,
)

SCENARIO_DATASET_VERSION = "1.0.0"


class EvidenceTurn(BaseModel):
    """One chronological exchange in an evaluation scenario.

    Attributes:
        user:
            Exact identity message.
        persona:
            Exact persona response.
        selected:
            Whether the exchange belongs to selected history.
        scene_position:
            Storyline scene position when the scenario uses Storyline mode.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    user: str = Field(min_length=1, description="Exact identity message.")
    persona: str = Field(min_length=1, description="Exact persona response.")
    selected: bool = Field(default=True, description="Selected-history membership.")
    scene_position: int | None = Field(
        default=None, ge=1, description="Optional Storyline scene position."
    )


class RelationshipState(BaseModel):
    """Portable relationship state.

    Attributes:
        revision:
            Projection replay revision.
        social:
            Qualitative social status.
        romantic:
            Qualitative romantic status.
        dynamic:
            Current interaction dynamic.
        trust:
            Current trust state.
        affection:
            Current affection state.
        milestones:
            Explicit milestones in replay order.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    revision: int = Field(default=0, ge=0, description="Projection replay revision.")
    social: RelationshipSocialStatus = Field(
        default=RelationshipSocialStatus.STRANGER,
        description="Qualitative social status.",
    )
    romantic: RelationshipRomanticStatus = Field(
        default=RelationshipRomanticStatus.NONE,
        description="Qualitative romantic status.",
    )
    dynamic: RelationshipDynamic = Field(
        default=RelationshipDynamic.NEUTRAL,
        description="Current interaction dynamic.",
    )
    trust: RelationshipTrust = Field(
        default=RelationshipTrust.UNKNOWN, description="Current trust state."
    )
    affection: RelationshipAffection = Field(
        default=RelationshipAffection.NEUTRAL,
        description="Current affection state.",
    )
    milestones: tuple[RelationshipMilestone, ...] = Field(
        default=(), description="Explicit milestones in replay order."
    )


class AdaptationState(BaseModel):
    """Portable active persona-adaptation value.

    Attributes:
        facet:
            Typed adaptation facet.
        value:
            Concise continuity-local behavior.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    facet: AdaptationFacet = Field(description="Typed adaptation facet.")
    value: str = Field(min_length=1, max_length=512, description="Adapted behavior.")


class CommandExpectation(BaseModel):
    """Rationale-independent command signature expected by a scenario.

    Attributes:
        kind:
            Stable evolution command discriminator.
        expected:
            Optional expected current value.
        value:
            Optional proposed replacement value.
        facet:
            Optional persona-adaptation facet.
        milestone:
            Optional explicit relationship milestone.
        evidence:
            One-based selected evidence turn positions.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[
        "set_social_status",
        "set_romantic_status",
        "set_dynamic",
        "set_trust",
        "set_affection",
        "record_relationship_milestone",
        "set_persona_adaptation",
        "remove_persona_adaptation",
    ] = Field(description="Stable command discriminator.")
    expected: str | None = Field(default=None, description="Expected current value.")
    value: str | None = Field(default=None, description="Proposed replacement value.")
    facet: AdaptationFacet | None = Field(default=None, description="Adaptation facet.")
    milestone: RelationshipMilestone | None = Field(
        default=None, description="Explicit relationship milestone."
    )
    evidence: tuple[int, ...] = Field(
        min_length=1, description="One-based selected evidence positions."
    )


class EvolutionScenario(BaseModel):
    """One versioned, deterministic evolution evaluation scenario.

    Attributes:
        dataset_version:
            Scenario schema and semantics version.
        name:
            Stable unique scenario name.
        tags:
            Behavioral capabilities exercised.
        mode:
            Ongoing or Storyline evidence shape.
        relationship_intent:
            User-selected relationship direction.
        boundaries:
            User-controlled restrictions.
        persona_definition:
            Authored core used for contradiction checks.
        starting_relationship:
            Projection before evaluating the source turn.
        starting_adaptations:
            Active adaptations before evaluation.
        evidence:
            Chronological exchanges, including deselected retry evidence.
        required_proposals:
            Command signatures that must be proposed.
        permitted_proposals:
            Optional acceptable command signatures.
        forbidden_proposals:
            Command signatures that violate scenario behavior.
        expected_outcome:
            Expected application decision.
        expected_reason:
            Expected stable rejection category.
        expected_relationship:
            Expected projection after policy evaluation.
        expected_adaptations:
            Expected active adaptations after policy evaluation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_version: Literal["1.0.0"] = Field(description="Dataset schema version.")
    name: str = Field(
        min_length=1, pattern=r"^[a-z0-9_]+$", description="Scenario name."
    )
    tags: tuple[str, ...] = Field(
        min_length=1, description="Behavioral capability tags."
    )
    mode: ContinuityMode = Field(
        default=ContinuityMode.ONGOING, description="Continuity evidence mode."
    )
    relationship_intent: RelationshipIntent = Field(
        description="User-selected relationship direction."
    )
    boundaries: tuple[Boundary, ...] = Field(
        default=(), description="User-controlled restrictions."
    )
    persona_definition: str = Field(
        default="A thoughtful, honest companion.",
        min_length=1,
        description="Authored immutable persona definition.",
    )
    starting_relationship: RelationshipState = Field(
        default_factory=RelationshipState,
        description="Projection before source evaluation.",
    )
    starting_adaptations: tuple[AdaptationState, ...] = Field(
        default=(), description="Active adaptations before evaluation."
    )
    evidence: tuple[EvidenceTurn, ...] = Field(
        min_length=1, description="Chronological scenario exchanges."
    )
    required_proposals: tuple[CommandExpectation, ...] = Field(
        default=(), description="Required command signatures."
    )
    permitted_proposals: tuple[CommandExpectation, ...] = Field(
        default=(), description="Optional acceptable command signatures."
    )
    forbidden_proposals: tuple[CommandExpectation, ...] = Field(
        default=(), description="Forbidden command signatures."
    )
    expected_outcome: EvolutionDecisionOutcome = Field(
        description="Expected application decision."
    )
    expected_reason: EvolutionRejectionReason | None = Field(
        default=None, description="Expected stable rejection category."
    )
    expected_relationship: RelationshipState = Field(
        default_factory=RelationshipState,
        description="Expected relationship projection after evaluation.",
    )
    expected_adaptations: tuple[AdaptationState, ...] = Field(
        default=(), description="Expected adaptations after evaluation."
    )

    @model_validator(mode="after")
    def validate_scenario(self) -> Self:
        """Require coherent decision, evidence, and expectation shapes.

        Returns:
            Validated scenario.

        Raises:
            ValueError:
                If the scenario cannot be evaluated deterministically.
        """

        if self.mode == ContinuityMode.TIMELINE:
            raise ValueError("Timeline evolution scenarios are deferred.")

        if not any(turn.selected for turn in self.evidence):
            raise ValueError("An evolution scenario requires selected evidence.")

        selected_count = sum(turn.selected for turn in self.evidence)
        expectations = (
            self.required_proposals
            + self.permitted_proposals
            + self.forbidden_proposals
        )
        if any(
            position > selected_count
            for item in expectations
            for position in item.evidence
        ):
            raise ValueError("Command expectations cite unavailable selected evidence.")

        if self.expected_outcome == EvolutionDecisionOutcome.REJECTED:
            if self.expected_reason is None:
                raise ValueError("Rejected scenarios require a reason.")
        elif self.expected_reason is not None:
            raise ValueError("Only rejected scenarios may declare a reason.")

        return self

    def build_snapshot(self) -> EvolutionSnapshot:
        """Build reproducible domain inputs from portable dataset values.

        Returns:
            Fully owned immutable evolution snapshot.
        """

        scope = EvolutionScope(
            identity_id=_scenario_uuid(self.name, "identity"),
            persona_id=_scenario_uuid(self.name, "persona"),
            continuity_id=_scenario_uuid(self.name, "continuity"),
        )
        selected = tuple(turn for turn in self.evidence if turn.selected)
        references = tuple(
            _build_reference(self, scope, index, turn)
            for index, turn in enumerate(selected, start=1)
        )
        evidence = tuple(
            EvolutionEvidence(
                reference=reference,
                user_content=turn.user,
                persona_content=turn.persona,
            )
            for reference, turn in zip(references, selected, strict=True)
        )
        relationship = self.starting_relationship
        return EvolutionSnapshot(
            scope=scope,
            mode=self.mode,
            identity=Identity(
                id=scope.identity_id,
                details=IdentityDetails(name="Evaluation identity"),
                is_frozen=True,
                is_default=False,
            ),
            persona=Persona(
                id=scope.persona_id,
                core=PersonaCore(
                    name="Evaluation persona", definition=self.persona_definition
                ),
                is_frozen=True,
            ),
            relationship_intent=self.relationship_intent,
            boundaries=self.boundaries,
            relationship=RelationshipProjection(
                scope=scope,
                **relationship.model_dump(),
            ),
            persona_adaptations=PersonaAdaptationProjection(
                scope=scope,
                revision=0,
                adaptations=tuple(
                    PersonaAdaptation(**item.model_dump())
                    for item in self.starting_adaptations
                ),
            ),
            evidence=evidence,
            source=references[-1],
        )


class PolicyEvaluation(BaseModel):
    """Policy decision and resulting replay projections.

    Attributes:
        decision:
            Terminal decision for the proposal.
        relationship:
            Relationship projection after evaluation.
        persona_adaptations:
            Adaptation projection after evaluation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: EvolutionDecision = Field(description="Terminal proposal decision.")
    relationship: RelationshipProjection = Field(
        description="Relationship projection after evaluation."
    )
    persona_adaptations: PersonaAdaptationProjection = Field(
        description="Adaptation projection after evaluation."
    )


class EvolutionEvaluationPolicy(Protocol):
    """Framework-neutral policy seam consumed by the evaluation runner."""

    def evaluate(
        self, snapshot: EvolutionSnapshot, proposal: EvolutionProposal
    ) -> PolicyEvaluation:
        """Validate a proposal and return its deterministic result.

        Args:
            snapshot:
                Immutable strategy input.
            proposal:
                Typed strategy output.

        Returns:
            Decision and replayed projections.
        """

        ...


class ScenarioResult(BaseModel):
    """Machine-readable metrics for one evaluated scenario.

    Attributes:
        name:
            Scenario name.
        tags:
            Scenario behavioral tags.
        schema_valid:
            Whether strategy and policy returned typed values.
        ownership_evidence_valid:
            Whether proposal ownership and evidence passed seam checks.
        required_proposal_recall:
            Fraction of required signatures proposed.
        forbidden_proposal_rate:
            Fraction of proposed signatures explicitly forbidden.
        hard_invariant_violations:
            Count of forbidden proposals or invalid seam output.
        no_change_correct:
            Whether expected and actual no-change behavior agree.
        policy_decision_correct:
            Whether outcome and reason match the scenario.
        actual_outcome:
            Terminal outcome returned by proposal validation.
        rejection_reason:
            Stable validator category when the proposal was rejected.
        projection_replay_correct:
            Whether both resulting projections match expected state.
        duplicate_effect_rate:
            Fraction of repeated command signatures.
        passed:
            Exact promotion-gate result for this scenario.
        error:
            Stable diagnostic when evaluation could not complete.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="Scenario name.")
    tags: tuple[str, ...] = Field(description="Behavioral capability tags.")
    schema_valid: bool = Field(description="Typed output validity.")
    ownership_evidence_valid: bool = Field(description="Scope and evidence validity.")
    required_proposal_recall: float = Field(
        ge=0.0, le=1.0, description="Required recall."
    )
    forbidden_proposal_rate: float = Field(
        ge=0.0, le=1.0, description="Forbidden rate."
    )
    hard_invariant_violations: int = Field(ge=0, description="Hard violation count.")
    no_change_correct: bool = Field(description="No-change correctness.")
    policy_decision_correct: bool = Field(description="Decision correctness.")
    actual_outcome: EvolutionDecisionOutcome | None = Field(
        default=None, description="Actual terminal validator outcome."
    )
    rejection_reason: EvolutionRejectionReason | None = Field(
        default=None, description="Actual stable rejection category."
    )
    projection_replay_correct: bool = Field(description="Replay correctness.")
    duplicate_effect_rate: float = Field(ge=0.0, le=1.0, description="Duplicate rate.")
    passed: bool = Field(description="Promotion-gate result.")
    error: str | None = Field(default=None, description="Evaluation diagnostic.")


class AggregateMetrics(BaseModel):
    """Aggregate deterministic metrics for one strategy-policy run.

    Attributes:
        scenario_count:
            Number of evaluated scenarios.
        passed_count:
            Number satisfying every hard gate.
        pass_rate:
            Fraction satisfying every hard gate.
        schema_validity:
            Mean schema-validity score.
        ownership_evidence_validity:
            Mean ownership and evidence score.
        required_proposal_recall:
            Mean required-proposal recall.
        forbidden_proposal_rate:
            Mean per-scenario forbidden-proposal rate.
        hard_invariant_violation_rate:
            Scenarios with a hard violation divided by scenarios.
        no_change_correctness:
            Mean no-change correctness.
        policy_acceptance_correctness:
            Mean decision correctness.
        projection_replay_correctness:
            Mean replay correctness.
        branch_fork_correctness:
            Replay correctness for branch or fork scenarios.
        correction_correctness:
            Replay correctness for correction scenarios.
        duplicate_effect_rate:
            Mean duplicate-effect rate.
        state_oscillation_correctness:
            Replay correctness for oscillation scenarios.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_count: int = Field(ge=0, description="Evaluated scenario count.")
    passed_count: int = Field(ge=0, description="Passing scenario count.")
    pass_rate: float = Field(ge=0.0, le=1.0, description="Scenario pass rate.")
    schema_validity: float = Field(ge=0.0, le=1.0, description="Schema validity.")
    ownership_evidence_validity: float = Field(
        ge=0.0, le=1.0, description="Ownership and evidence validity."
    )
    required_proposal_recall: float = Field(
        ge=0.0, le=1.0, description="Required recall."
    )
    forbidden_proposal_rate: float = Field(
        ge=0.0, le=1.0, description="Forbidden rate."
    )
    hard_invariant_violation_rate: float = Field(
        ge=0.0, le=1.0, description="Hard-invariant violation rate."
    )
    no_change_correctness: float = Field(ge=0.0, le=1.0, description="No-change score.")
    policy_acceptance_correctness: float = Field(
        ge=0.0, le=1.0, description="Decision correctness."
    )
    projection_replay_correctness: float = Field(
        ge=0.0, le=1.0, description="Projection replay correctness."
    )
    branch_fork_correctness: float = Field(
        ge=0.0, le=1.0, description="Branch and fork correctness."
    )
    correction_correctness: float = Field(
        ge=0.0, le=1.0, description="Correction correctness."
    )
    duplicate_effect_rate: float = Field(
        ge=0.0, le=1.0, description="Duplicate-effect rate."
    )
    state_oscillation_correctness: float = Field(
        ge=0.0, le=1.0, description="State-oscillation correctness."
    )


class EvaluationRun(BaseModel):
    """Complete serializable output for an evaluation run.

    Attributes:
        dataset_version:
            Version shared by all loaded scenarios.
        strategy:
            Versioned strategy identifier.
        results:
            Ordered per-scenario results.
        metrics:
            Aggregate deterministic metrics.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_version: str = Field(description="Scenario dataset version.")
    strategy: str = Field(description="Versioned strategy identifier.")
    results: tuple[ScenarioResult, ...] = Field(description="Per-scenario results.")
    metrics: AggregateMetrics = Field(description="Aggregate metrics.")


def load_scenarios(path: Path) -> tuple[EvolutionScenario, ...]:
    """Load and validate a versioned JSONL scenario dataset.

    Args:
        path:
            JSONL dataset path.

    Returns:
        Validated scenarios in file order.

    Raises:
        ValueError:
            If the dataset is empty, mixed-version, or has duplicate names.
    """

    scenarios = tuple(
        EvolutionScenario.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    if not scenarios:
        raise ValueError("Evolution scenario dataset cannot be empty.")
    if len({scenario.name for scenario in scenarios}) != len(scenarios):
        raise ValueError("Evolution scenario names must be unique.")
    if {scenario.dataset_version for scenario in scenarios} != {
        SCENARIO_DATASET_VERSION
    }:
        raise ValueError("Evolution scenario dataset versions cannot be mixed.")
    return scenarios


def _scenario_uuid(name: str, component: str) -> UUID:
    """Derive a reproducible UUID for a scenario component.

    Args:
        name:
            Scenario name.
        component:
            Component discriminator.

    Returns:
        Stable UUID value.
    """

    return uuid5(NAMESPACE_URL, f"chat-buddy:evolution:{name}:{component}")


def _build_reference(
    scenario: EvolutionScenario,
    scope: EvolutionScope,
    index: int,
    turn: EvidenceTurn,
) -> EvolutionEvidenceReference:
    """Build one deterministic selected evidence reference.

    Args:
        scenario:
            Owning scenario.
        scope:
            Generated scenario scope.
        index:
            One-based selected turn position.
        turn:
            Portable evidence content.

    Returns:
        Exact reproducible evidence reference.
    """

    storyline = scenario.mode == ContinuityMode.STORYLINE
    scene_position = turn.scene_position or index if storyline else None
    return EvolutionEvidenceReference(
        scope=scope,
        kind=(
            EvolutionEvidenceKind.STORYLINE_CHECKPOINT
            if storyline
            else EvolutionEvidenceKind.ONGOING_TURN
        ),
        conversation_id=_scenario_uuid(
            scenario.name, f"conversation:{scene_position or 1}"
        ),
        scene_id=(
            _scenario_uuid(scenario.name, f"scene:{scene_position}")
            if storyline
            else None
        ),
        scene_position=scene_position,
        user_message_id=_scenario_uuid(scenario.name, f"user:{index}"),
        user_sequence=index * 2 - 1,
        persona_message_id=_scenario_uuid(scenario.name, f"persona:{index}"),
        persona_sequence=index * 2,
    )
