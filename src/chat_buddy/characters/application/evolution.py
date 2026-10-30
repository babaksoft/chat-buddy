"""Replaceable evolution strategies, validation, and configuration resolution."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field

from chat_buddy.characters.domain import (
    MAX_EVOLUTION_COMMANDS,
    EvolutionCommand,
    EvolutionConfiguration,
    EvolutionDecision,
    EvolutionDecisionOutcome,
    EvolutionEvent,
    EvolutionEvidenceReference,
    EvolutionExperimentResult,
    EvolutionProposal,
    EvolutionRejectionReason,
    EvolutionSnapshot,
    EvolutionStrategy,
    EvolutionThresholdAssessment,
    EvolutionThresholdPolicy,
    PersonaAdaptation,
    PersonaAdaptationProjection,
    RecordRelationshipMilestoneCommand,
    RelationshipDynamic,
    RelationshipMilestone,
    RelationshipProjection,
    RelationshipRomanticStatus,
    RelationshipSocialStatus,
    RemovePersonaAdaptationCommand,
    SetAffectionCommand,
    SetDynamicCommand,
    SetPersonaAdaptationCommand,
    SetRomanticStatusCommand,
    SetSocialStatusCommand,
    SetTrustCommand,
    StrategyIdentity,
)

BASELINE_EVOLUTION_CONFIGURATION = EvolutionConfiguration(
    selector=StrategyIdentity(name="baseline.exact_evidence", version="1.0.0"),
    strategy=StrategyIdentity(name="baseline.no_change", version="1.0.0"),
    threshold_policy=StrategyIdentity(name="baseline.strict", version="1.0.0"),
    schema_identity=StrategyIdentity(name="evolution.typed_commands", version="1.0.0"),
)


class EvolutionValidationResult(BaseModel):
    """Atomic proposal decision and the projections it would produce.

    Attributes:
        decision:
            Terminal deterministic validation decision.
        relationship:
            Original or atomically updated relationship projection.
        persona_adaptations:
            Original or atomically updated adaptation projection.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: EvolutionDecision = Field(description="Terminal validation decision.")
    relationship: RelationshipProjection = Field(
        description="Relationship projection after the decision."
    )
    persona_adaptations: PersonaAdaptationProjection = Field(
        description="Persona-adaptation projection after the decision."
    )


class NoChangeEvolutionStrategy:
    """Baseline strategy that explicitly proposes no evolution."""

    _STRATEGY_ID = StrategyIdentity(name="baseline.no_change", version="1.0.0")

    def __init__(
        self,
        configuration: EvolutionConfiguration = BASELINE_EVOLUTION_CONFIGURATION,
    ) -> None:
        """Bind the exact configuration recorded by empty proposals.

        Args:
            configuration:
                Versioned configuration whose strategy must be this implementation.

        Raises:
            ValueError:
                If the configuration names a different proposal strategy.
        """

        if configuration.strategy != self._STRATEGY_ID:
            raise ValueError("No-change configuration has a different strategy.")
        self._configuration = configuration

    @property
    def strategy_id(self) -> StrategyIdentity:
        """Return the stable baseline strategy identity.

        Returns:
            Baseline name and behavior version.
        """

        return self._STRATEGY_ID

    def propose(self, snapshot: EvolutionSnapshot) -> EvolutionProposal:
        """Return a versioned no-change proposal for the supplied scope.

        Args:
            snapshot:
                Validated snapshots and eligible conversation evidence.

        Returns:
            Empty detached proposal with baseline provenance.
        """

        return EvolutionProposal(
            id=uuid4(),
            scope=snapshot.scope,
            expected_relationship_revision=snapshot.relationship.revision,
            expected_adaptation_revision=snapshot.persona_adaptations.revision,
            source=snapshot.source,
            provenance=self._configuration.provenance(),
        )


class DeterministicFixtureEvolutionStrategy:
    """Test strategy returning prevalidated commands by continuity."""

    _STRATEGY_ID = StrategyIdentity(name="fixture.deterministic", version="1.0.0")

    def __init__(
        self,
        commands: Mapping[UUID, tuple[EvolutionCommand, ...]],
        configuration: EvolutionConfiguration,
    ) -> None:
        """Copy deterministic fixture commands and bind their provenance.

        Args:
            commands:
                Typed commands indexed by continuity identifier.
            configuration:
                Exact fixture configuration recorded on proposals.

        Raises:
            ValueError:
                If the configuration names a different strategy.
        """

        if configuration.strategy != self._STRATEGY_ID:
            raise ValueError("Fixture configuration has a different strategy.")

        self._commands = dict(commands)
        self._configuration = configuration

    @property
    def strategy_id(self) -> StrategyIdentity:
        """Return the deterministic fixture identity.

        Returns:
            Stable fixture strategy identity.
        """

        return self._STRATEGY_ID

    def propose(self, snapshot: EvolutionSnapshot) -> EvolutionProposal:
        """Return the commands registered for the snapshot continuity.

        Args:
            snapshot:
                Immutable scenario or test snapshot.

        Returns:
            Deterministic typed proposal with exact configured provenance.
        """

        return EvolutionProposal(
            id=uuid5(
                snapshot.scope.continuity_id,
                f"{snapshot.source.persona_message_id}:{self.strategy_id.version}",
            ),
            scope=snapshot.scope,
            expected_relationship_revision=snapshot.relationship.revision,
            expected_adaptation_revision=snapshot.persona_adaptations.revision,
            source=snapshot.source,
            provenance=self._configuration.provenance(),
            commands=self._commands.get(snapshot.scope.continuity_id, ()),
        )


class StrictBaselineEvolutionThresholdPolicy:
    """Conservative count thresholds independent of hard validation."""

    _POLICY_ID = StrategyIdentity(name="baseline.strict", version="1.0.0")

    @property
    def policy_id(self) -> StrategyIdentity:
        """Return the strict baseline policy identity.

        Returns:
            Stable policy name and behavior version.
        """

        return self._POLICY_ID

    def assess(
        self, snapshot: EvolutionSnapshot, command: EvolutionCommand
    ) -> EvolutionThresholdAssessment:
        """Require two turns for gradual state and one for immediate changes.

        Dynamic changes, explicit milestones, and persona-adaptation commands may
        pass the calibration threshold with one cited turn. Social, romantic,
        trust, and affection changes require two distinct cited turns. Separate
        hard validators remain responsible for evidence eligibility, explicitness,
        intent, transition legality, boundaries, and persona-core compatibility.

        Args:
            snapshot:
                Immutable eligible evidence context.
            command:
                Typed proposed change.

        Returns:
            Counted, internally consistent threshold assessment.
        """

        del snapshot
        immediate = isinstance(
            command,
            (
                SetDynamicCommand,
                RecordRelationshipMilestoneCommand,
                SetPersonaAdaptationCommand,
                RemovePersonaAdaptationCommand,
            ),
        )
        required = 1 if immediate else 2
        observed = len(set(command.sources))
        return EvolutionThresholdAssessment(
            satisfied=observed >= required,
            required_distinct_turns=required,
            observed_distinct_turns=observed,
        )


class EvolutionProposalValidator:
    """Enforce hard evolution invariants and one versioned threshold policy."""

    def __init__(
        self,
        threshold_policy: EvolutionThresholdPolicy,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind the only replaceable portion of proposal validation.

        Args:
            threshold_policy:
                Versioned calibration for gradual evidence counts.
            clock:
                Optional aware event-time source for deterministic tests.
        """

        self._threshold_policy = threshold_policy
        self._clock = clock or (lambda: datetime.now(UTC))

    def evaluate(
        self, snapshot: EvolutionSnapshot, proposal: EvolutionProposal
    ) -> EvolutionValidationResult:
        """Validate and project one proposal as an atomic change set.

        Rejection checks have stable precedence. A failed command leaves both
        projections unchanged; a successful proposal produces one event per
        command and increments only the projection affected by that command.

        Args:
            snapshot:
                Immutable current state and selected eligible evidence.
            proposal:
                Untrusted typed strategy output.

        Returns:
            Terminal decision and original or atomically updated projections.
        """

        reason = self._rejection_reason(snapshot, proposal)
        if reason is not None:
            return self._result(
                snapshot,
                EvolutionDecision(
                    proposal_id=proposal.id,
                    outcome=EvolutionDecisionOutcome.REJECTED,
                    reason=reason,
                ),
            )
        if not proposal.commands:
            return self._result(
                snapshot,
                EvolutionDecision(
                    proposal_id=proposal.id,
                    outcome=EvolutionDecisionOutcome.NO_CHANGE,
                ),
            )

        relationship = snapshot.relationship
        adaptations = snapshot.persona_adaptations
        events: list[EvolutionEvent] = []
        created_at = self._clock()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("Evolution validation clock must be timezone-aware.")

        for position, command in enumerate(proposal.commands):
            relationship, adaptations = _apply_command(
                relationship, adaptations, command
            )
            events.append(
                EvolutionEvent(
                    id=uuid5(proposal.id, f"event:{position}"),
                    proposal_id=proposal.id,
                    scope=snapshot.scope,
                    command=command,
                    relationship_revision=relationship.revision,
                    adaptation_revision=adaptations.revision,
                    provenance=proposal.provenance,
                    created_at=created_at,
                )
            )

        return EvolutionValidationResult(
            decision=EvolutionDecision(
                proposal_id=proposal.id,
                outcome=EvolutionDecisionOutcome.APPLIED,
                events=tuple(events),
            ),
            relationship=relationship,
            persona_adaptations=adaptations,
        )

    def _rejection_reason(
        self, snapshot: EvolutionSnapshot, proposal: EvolutionProposal
    ) -> EvolutionRejectionReason | None:
        """Return the first stable failed validator category.

        Args:
            snapshot:
                Immutable current state and evidence.
            proposal:
                Candidate atomic proposal.

        Returns:
            First deterministic rejection reason, or None when valid.
        """

        if (
            proposal.scope != snapshot.scope
            or proposal.source.scope != snapshot.scope
            or proposal.provenance.policy != self._threshold_policy.policy_id
        ):
            return EvolutionRejectionReason.OWNERSHIP

        if len(proposal.commands) > MAX_EVOLUTION_COMMANDS or len(
            {_command_target_key(command) for command in proposal.commands}
        ) != len(proposal.commands):
            return EvolutionRejectionReason.PROPOSAL_BOUNDS

        if (
            proposal.expected_relationship_revision != snapshot.relationship.revision
            or proposal.expected_adaptation_revision
            != snapshot.persona_adaptations.revision
            or any(
                not _expected_value_matches(snapshot, command)
                for command in proposal.commands
            )
        ):
            return EvolutionRejectionReason.EXPECTED_PROJECTION

        eligible = {evidence.reference for evidence in snapshot.evidence}
        if (
            proposal.source != snapshot.source
            or any(
                source.scope != snapshot.scope or source not in eligible
                for command in proposal.commands
                for source in command.sources
            )
            or any(
                snapshot.source not in command.sources for command in proposal.commands
            )
        ):
            return EvolutionRejectionReason.EVIDENCE

        if any(_violates_boundary(snapshot, command) for command in proposal.commands):
            return EvolutionRejectionReason.USER_BOUNDARY

        if any(_violates_intent(snapshot, command) for command in proposal.commands):
            return EvolutionRejectionReason.RELATIONSHIP_INTENT

        if any(
            not _transition_is_allowed(snapshot, command)
            for command in proposal.commands
        ):
            return EvolutionRejectionReason.TRANSITION

        if any(
            not self._threshold_policy.assess(snapshot, command).satisfied
            for command in proposal.commands
        ):
            return EvolutionRejectionReason.THRESHOLD

        if any(
            _contradicts_persona_core(snapshot, command)
            for command in proposal.commands
        ):
            return EvolutionRejectionReason.PERSONA_CORE

        if any(
            not _adaptation_is_allowed(snapshot, command)
            for command in proposal.commands
        ):
            return EvolutionRejectionReason.ADAPTATION_FACET

        return None

    @staticmethod
    def _result(
        snapshot: EvolutionSnapshot, decision: EvolutionDecision
    ) -> EvolutionValidationResult:
        """Pair a non-applied decision with unchanged projections.

        Args:
            snapshot:
                Immutable current projections.
            decision:
                Rejected or no-change terminal decision.

        Returns:
            Complete unchanged validation result.
        """

        return EvolutionValidationResult(
            decision=decision,
            relationship=snapshot.relationship,
            persona_adaptations=snapshot.persona_adaptations,
        )


class NoOpEvolutionExperimentReporter:
    """Default reporter that deliberately performs no external work."""

    def report(self, result: EvolutionExperimentResult) -> None:
        """Accept and discard one typed experiment result.

        Args:
            result:
                Complete framework-neutral experiment result.
        """

        del result


class ContinuityStableEvolutionConfigurationResolver:
    """Deterministically assign configurations with optional explicit overrides."""

    def __init__(
        self,
        configurations: tuple[EvolutionConfiguration, ...],
        assignments: Mapping[UUID, EvolutionConfiguration] | None = None,
    ) -> None:
        """Bind available configurations and explicit continuity assignments.

        Args:
            configurations:
                Non-empty ordered experiment configurations.
            assignments:
                Explicit stable assignments overriding deterministic allocation.

        Raises:
            ValueError:
                If no configuration is available.
        """

        if not configurations:
            raise ValueError("Evolution configuration resolution requires a choice.")

        self._configurations = configurations
        self._assignments = dict(assignments or {})

    def resolve(self, continuity_id: UUID) -> EvolutionConfiguration:
        """Return the same assignment for every boundary in one continuity.

        Args:
            continuity_id:
                Continuity receiving an evolution effect.

        Returns:
            Explicit assignment or deterministic bucket configuration.
        """

        assigned = self._assignments.get(continuity_id)
        if assigned is not None:
            return assigned

        return self._configurations[continuity_id.int % len(self._configurations)]


class EvolutionEvaluator:
    """Invoke a replaceable strategy and enforce seam-level provenance."""

    def __init__(
        self,
        strategy: EvolutionStrategy,
        configuration: EvolutionConfiguration | None = None,
    ) -> None:
        """Initialize the evaluator with a replaceable strategy.

        Args:
            strategy:
                Evolution proposal implementation.
            configuration:
                Optional message-boundary configuration enforced on the result.

        Raises:
            ValueError:
                If the configured strategy identity does not match the component.
        """

        if configuration is not None and configuration.strategy != strategy.strategy_id:
            raise ValueError("Evolution configuration strategy does not match.")

        self._strategy = strategy
        self._configuration = configuration

    def evaluate(self, snapshot: EvolutionSnapshot) -> EvolutionProposal:
        """Evaluate inputs and reject foreign provenance or evidence references.

        This validates only the strategy seam. Future relationship transitions and
        durable state changes still require established domain validation.

        Args:
            snapshot:
                Immutable scoped snapshots and eligible evidence.

        Returns:
            Detached, provenance-checked proposal.

        Raises:
            ValueError:
                If the strategy mislabels its result or cites ineligible evidence.
        """

        proposal = self._strategy.propose(snapshot)
        if proposal.provenance.strategy != self._strategy.strategy_id:
            raise ValueError("Evolution proposal strategy provenance is invalid.")
        if (
            self._configuration is not None
            and proposal.provenance != self._configuration.provenance()
        ):
            raise ValueError("Evolution proposal configuration provenance is invalid.")

        if proposal.scope != snapshot.scope:
            raise ValueError("Evolution proposal scope does not match its inputs.")
        if proposal.source != snapshot.source:
            raise ValueError("Evolution proposal source does not match its inputs.")
        if (
            proposal.expected_relationship_revision != snapshot.relationship.revision
            or proposal.expected_adaptation_revision
            != snapshot.persona_adaptations.revision
        ):
            raise ValueError("Evolution proposal projection revision is stale.")

        eligible: set[EvolutionEvidenceReference] = {
            evidence.reference for evidence in snapshot.evidence
        }
        cited = {source for command in proposal.commands for source in command.sources}
        if not cited.issubset(eligible):
            raise ValueError("Evolution proposal cites ineligible evidence.")

        return proposal


def _command_target_key(command: EvolutionCommand) -> str:
    """Return the unique projection target of a command.

    Args:
        command:
            Typed relationship or adaptation command.

    Returns:
        Stable target identity within an atomic proposal.
    """

    if isinstance(
        command, (SetPersonaAdaptationCommand, RemovePersonaAdaptationCommand)
    ):
        return f"adaptation:{command.facet.value}"

    if isinstance(
        command, (SetRomanticStatusCommand, RecordRelationshipMilestoneCommand)
    ):
        return "relationship:romantic"

    return f"relationship:{command.kind.removeprefix('set_')}"


def _expected_value_matches(
    snapshot: EvolutionSnapshot, command: EvolutionCommand
) -> bool:
    """Check a command's compare-and-set value against current projections.

    Args:
        snapshot:
            Current immutable projections.
        command:
            Candidate typed command.

    Returns:
        Whether the command observed the exact current target value.
    """

    relationship = snapshot.relationship
    if isinstance(command, SetSocialStatusCommand):
        return command.expected == relationship.social
    if isinstance(
        command, (SetRomanticStatusCommand, RecordRelationshipMilestoneCommand)
    ):
        return command.expected == relationship.romantic
    if isinstance(command, SetDynamicCommand):
        return command.expected == relationship.dynamic
    if isinstance(command, SetTrustCommand):
        return command.expected == relationship.trust
    if isinstance(command, SetAffectionCommand):
        return command.expected == relationship.affection

    active = {
        item.facet: item.value for item in snapshot.persona_adaptations.adaptations
    }
    if isinstance(command, SetPersonaAdaptationCommand):
        return command.expected == active.get(command.facet)
    return isinstance(command, RemovePersonaAdaptationCommand) and (
        command.expected == active.get(command.facet)
    )


def _violates_boundary(snapshot: EvolutionSnapshot, command: EvolutionCommand) -> bool:
    """Determine whether a command weakens a user-controlled boundary.

    Args:
        snapshot:
            User-selected immutable constraints.
        command:
            Candidate change.

    Returns:
        Whether applying the command would conflict with a boundary.
    """

    boundaries = set(snapshot.boundaries)
    romantic = _romantic_target(command)
    if "no_romance" in boundaries and romantic not in {
        None,
        RelationshipRomanticStatus.NONE,
    }:
        return True
    if "no_flirting" in boundaries and romantic == RelationshipRomanticStatus.INTEREST:
        return True
    if isinstance(command, SetPersonaAdaptationCommand):
        value = command.value.casefold()
        if "no_flirting" in boundaries and "flirt" in value:
            return True
        if "no_physical_intimacy" in boundaries and any(
            term in value for term in ("physical intimacy", "kiss", "touch", "cuddle")
        ):
            return True
    return False


def _violates_intent(snapshot: EvolutionSnapshot, command: EvolutionCommand) -> bool:
    """Determine whether a relationship command conflicts with user intent.

    Args:
        snapshot:
            User-selected relationship direction.
        command:
            Candidate change.

    Returns:
        Whether platonic intent prohibits the romantic target.
    """

    romantic = _romantic_target(command)
    return snapshot.relationship_intent.value == "platonic" and romantic not in {
        None,
        RelationshipRomanticStatus.NONE,
    }


def _transition_is_allowed(
    snapshot: EvolutionSnapshot, command: EvolutionCommand
) -> bool:
    """Apply conservative baseline transition graphs and explicitness rules.

    Args:
        snapshot:
            Current state and exact cited text.
        command:
            Candidate typed transition.

    Returns:
        Whether the transition is legal and explicitly evidenced when required.
    """

    if isinstance(command, SetSocialStatusCommand):
        order = list(RelationshipSocialStatus)
        current = order.index(command.expected)
        target = order.index(command.value)
        return 0 < target - current <= 2 or target - current == -1
    if isinstance(command, SetRomanticStatusCommand):
        romantic_transitions = {
            (RelationshipRomanticStatus.NONE, RelationshipRomanticStatus.INTEREST),
            (RelationshipRomanticStatus.INTEREST, RelationshipRomanticStatus.NONE),
            (RelationshipRomanticStatus.INTEREST, RelationshipRomanticStatus.DATING),
            (RelationshipRomanticStatus.DATING, RelationshipRomanticStatus.INTEREST),
        }
        return (
            command.expected,
            command.value,
        ) in romantic_transitions and _has_explicit_romance(snapshot, command)
    if isinstance(command, SetDynamicCommand):
        return _has_explicit_dynamic(snapshot, command)
    if isinstance(command, (SetTrustCommand, SetAffectionCommand)):
        return True
    if isinstance(command, RecordRelationshipMilestoneCommand):
        milestone_transitions = {
            RelationshipMilestone.PARTNERSHIP: {
                (RelationshipRomanticStatus.DATING, RelationshipRomanticStatus.PARTNER)
            },
            RelationshipMilestone.ENGAGEMENT: {
                (RelationshipRomanticStatus.PARTNER, RelationshipRomanticStatus.ENGAGED)
            },
            RelationshipMilestone.MARRIAGE: {
                (RelationshipRomanticStatus.ENGAGED, RelationshipRomanticStatus.SPOUSE)
            },
            RelationshipMilestone.BREAKUP: {
                (status, RelationshipRomanticStatus.NONE)
                for status in (
                    RelationshipRomanticStatus.DATING,
                    RelationshipRomanticStatus.PARTNER,
                    RelationshipRomanticStatus.ENGAGED,
                    RelationshipRomanticStatus.SPOUSE,
                )
            },
            RelationshipMilestone.RECONCILIATION: {
                (RelationshipRomanticStatus.NONE, RelationshipRomanticStatus.DATING),
                (RelationshipRomanticStatus.NONE, RelationshipRomanticStatus.PARTNER),
            },
        }
        return (
            command.expected,
            command.value,
        ) in milestone_transitions[
            command.milestone
        ] and _has_explicit_milestone(snapshot, command)
    return True


def _has_explicit_romance(
    snapshot: EvolutionSnapshot, command: SetRomanticStatusCommand
) -> bool:
    """Require direct, non-uncertain language for romantic-state inference.

    Args:
        snapshot:
            Exact eligible evidence text.
        command:
            Romantic transition and cited sources.

    Returns:
        Whether cited text directly describes romance.
    """

    text = _cited_text(snapshot, command)
    return not _is_uncertain(text) and any(
        term in text
        for term in ("romantic", "attracted", "crush", "in love", "date", "dating")
    )


def _has_explicit_dynamic(
    snapshot: EvolutionSnapshot, command: SetDynamicCommand
) -> bool:
    """Require one strong textual signal for a current interaction dynamic.

    Args:
        snapshot:
            Exact eligible evidence text.
        command:
            Proposed current dynamic.

    Returns:
        Whether the cited exchange directly signals the target dynamic.
    """

    terms = {
        RelationshipDynamic.NEUTRAL: ("neutral", "calm", "ordinary"),
        RelationshipDynamic.COMFORTABLE: ("comfortable", "at ease", "relaxed", "safe"),
        RelationshipDynamic.AWKWARD: ("awkward", "uncomfortable", "uneasy"),
        RelationshipDynamic.TENSE: ("tense", "angry", "upset", "conflict", "argue"),
        RelationshipDynamic.ESTRANGED: (
            "estranged",
            "keep our distance",
            "no longer speak",
        ),
    }
    text = _cited_text(snapshot, command)
    return not _is_uncertain(text) and any(
        term in text for term in terms[command.value]
    )


def _has_explicit_milestone(
    snapshot: EvolutionSnapshot, command: RecordRelationshipMilestoneCommand
) -> bool:
    """Require unambiguous cited narrative language for a major milestone.

    Args:
        snapshot:
            Exact eligible evidence text.
        command:
            Proposed named milestone.

    Returns:
        Whether cited evidence explicitly names the event.
    """

    terms = {
        RelationshipMilestone.PARTNERSHIP: ("be my partner", "we are partners"),
        RelationshipMilestone.ENGAGEMENT: ("marry me", "engaged", "fiance"),
        RelationshipMilestone.MARRIAGE: (
            "married",
            "wedding",
            "husband",
            "wife",
            "spouse",
        ),
        RelationshipMilestone.BREAKUP: ("break up", "relationship is over", "separate"),
        RelationshipMilestone.RECONCILIATION: (
            "reconcile",
            "get back together",
            "take me back",
        ),
    }
    text = _cited_text(snapshot, command)
    return not _is_uncertain(text) and any(
        term in text for term in terms[command.milestone]
    )


def _contradicts_persona_core(
    snapshot: EvolutionSnapshot, command: EvolutionCommand
) -> bool:
    """Reject adaptations that directly negate an authored core constraint.

    Args:
        snapshot:
            Immutable authored persona core.
        command:
            Candidate adaptation command.

    Returns:
        Whether a set adaptation repeats a prohibited core action.
    """

    if not isinstance(command, SetPersonaAdaptationCommand):
        return False

    definition = snapshot.persona.core.definition.casefold()
    prohibited = re.findall(
        r"(?:never|without|does not|do not|must not)\s+([^.;,]+)", definition
    )
    value_words = {
        _word_stem(word) for word in re.findall(r"[a-z]+", command.value.casefold())
    }

    for phrase in prohibited:
        words = [
            _word_stem(word)
            for word in re.findall(r"[a-z]+", phrase)
            if word not in {"a", "an", "the", "their", "your", "user", "identity"}
        ]
        if words and words[0] in value_words:
            return True

    return False


def _adaptation_is_allowed(
    snapshot: EvolutionSnapshot, command: EvolutionCommand
) -> bool:
    """Keep adaptations behavioral, supported, and within the typed vocabulary.

    Args:
        snapshot:
            Exact eligible evidence and active adaptations.
        command:
            Candidate adaptation change.

    Returns:
        Whether the command represents behavior rather than factual memory.
    """

    del snapshot
    if not isinstance(command, SetPersonaAdaptationCommand):
        return True

    value = command.value.casefold()
    factual = re.search(
        r"^(?:the )?(?:user|identity)\s+(?:is|was|has|had|lives?|moved|works?|likes?|owns?)\b",
        value,
    )

    return factual is None and not value.startswith(("remember ", "recall "))


def _apply_command(
    relationship: RelationshipProjection,
    adaptations: PersonaAdaptationProjection,
    command: EvolutionCommand,
) -> tuple[RelationshipProjection, PersonaAdaptationProjection]:
    """Apply one already validated command to detached projections.

    Args:
        relationship:
            Current detached relationship projection.
        adaptations:
            Current detached persona-adaptation projection.
        command:
            Fully validated atomic command.

    Returns:
        Updated relationship and adaptation projections.
    """

    if isinstance(command, SetSocialStatusCommand):
        relationship = relationship.model_copy(
            update={"revision": relationship.revision + 1, "social": command.value}
        )
    elif isinstance(command, SetRomanticStatusCommand):
        relationship = relationship.model_copy(
            update={"revision": relationship.revision + 1, "romantic": command.value}
        )
    elif isinstance(command, SetDynamicCommand):
        relationship = relationship.model_copy(
            update={"revision": relationship.revision + 1, "dynamic": command.value}
        )
    elif isinstance(command, SetTrustCommand):
        relationship = relationship.model_copy(
            update={"revision": relationship.revision + 1, "trust": command.value}
        )
    elif isinstance(command, SetAffectionCommand):
        relationship = relationship.model_copy(
            update={"revision": relationship.revision + 1, "affection": command.value}
        )
    elif isinstance(command, RecordRelationshipMilestoneCommand):
        relationship = relationship.model_copy(
            update={
                "revision": relationship.revision + 1,
                "romantic": command.value,
                "milestones": relationship.milestones + (command.milestone,),
            }
        )
    else:
        current = list(adaptations.adaptations)
        if isinstance(command, SetPersonaAdaptationCommand):
            replacement = PersonaAdaptation(facet=command.facet, value=command.value)
            for index, item in enumerate(current):
                if item.facet == command.facet:
                    current[index] = replacement
                    break
            else:
                current.append(replacement)
        else:
            current = [item for item in current if item.facet != command.facet]
        adaptations = adaptations.model_copy(
            update={
                "revision": adaptations.revision + 1,
                "adaptations": tuple(current),
            }
        )

    return relationship, adaptations


def _romantic_target(command: EvolutionCommand) -> RelationshipRomanticStatus | None:
    """Return a romantic target for commands that have one.

    Args:
        command:
            Candidate evolution command.

    Returns:
        Target romantic status, or None for another projection dimension.
    """

    if isinstance(
        command, (SetRomanticStatusCommand, RecordRelationshipMilestoneCommand)
    ):
        return command.value

    return None


def _cited_text(snapshot: EvolutionSnapshot, command: EvolutionCommand) -> str:
    """Combine only the exact exchanges cited by a command.

    Args:
        snapshot:
            Eligible exact evidence text.
        command:
            Command with validated evidence references.

    Returns:
        Case-folded cited user and persona content.
    """

    by_reference = {item.reference: item for item in snapshot.evidence}
    return " ".join(
        f"{by_reference[source].user_content} {by_reference[source].persona_content}"
        for source in command.sources
    ).casefold()


def _is_uncertain(text: str) -> bool:
    """Identify baseline language that cannot establish an explicit event.

    Args:
        text:
            Case-folded cited evidence text.

    Returns:
        Whether uncertainty markers occur in the evidence.
    """

    return any(
        term in text for term in ("maybe", "perhaps", "someday", "might", "could")
    )


def _word_stem(word: str) -> str:
    """Normalize simple English inflections for core-constraint comparison.

    Args:
        word:
            Lowercase alphabetic token.

    Returns:
        Conservatively normalized token.
    """

    if word.endswith("ing") and len(word) > 5:
        return word[:-3]
    if word.endswith("es") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and len(word) > 3:
        return word[:-1]
    return word
