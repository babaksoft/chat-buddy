"""Replaceable, non-persistent evolution components and configuration resolution."""

from collections.abc import Mapping
from uuid import UUID, uuid4, uuid5

from chat_buddy.characters.domain import (
    EvolutionCommand,
    EvolutionConfiguration,
    EvolutionEvidenceReference,
    EvolutionExperimentResult,
    EvolutionProposal,
    EvolutionSnapshot,
    EvolutionStrategy,
    EvolutionThresholdAssessment,
    RecordRelationshipMilestoneCommand,
    RemovePersonaAdaptationCommand,
    SetDynamicCommand,
    SetPersonaAdaptationCommand,
    StrategyIdentity,
)

BASELINE_EVOLUTION_CONFIGURATION = EvolutionConfiguration(
    selector=StrategyIdentity(name="baseline.exact_evidence", version="1.0.0"),
    strategy=StrategyIdentity(name="baseline.no_change", version="1.0.0"),
    threshold_policy=StrategyIdentity(name="baseline.strict", version="1.0.0"),
    schema_identity=StrategyIdentity(name="evolution.typed_commands", version="1.0.0"),
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
