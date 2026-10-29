"""Replaceable, non-persistent evolution strategy providers."""

from uuid import uuid4

from chat_buddy.characters.domain import (
    EvolutionEvidenceReference,
    EvolutionProposal,
    EvolutionProvenance,
    EvolutionSnapshot,
    EvolutionStrategy,
    StrategyIdentity,
)


class NoChangeEvolutionStrategy:
    """Baseline strategy that explicitly proposes no evolution."""

    _STRATEGY_ID = StrategyIdentity(name="baseline.no_change", version="1.0.0")
    _SELECTOR_ID = StrategyIdentity(name="baseline.exact_evidence", version="1.0.0")
    _POLICY_ID = StrategyIdentity(name="baseline.strict", version="1.0.0")
    _SCHEMA_ID = StrategyIdentity(name="evolution.typed_commands", version="1.0.0")

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
            provenance=EvolutionProvenance(
                selector=self._SELECTOR_ID,
                strategy=self.strategy_id,
                policy=self._POLICY_ID,
                schema_identity=self._SCHEMA_ID,
            ),
        )


class EvolutionEvaluator:
    """Invoke a replaceable strategy and enforce seam-level provenance."""

    def __init__(self, strategy: EvolutionStrategy) -> None:
        """Initialize the evaluator with a replaceable strategy.

        Args:
            strategy:
                Evolution proposal implementation.
        """

        self._strategy = strategy

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
