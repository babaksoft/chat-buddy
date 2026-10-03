"""Replaceable, non-persistent evolution strategy providers."""

from chat_buddy.characters.domain import (
    EvolutionEvidenceReference,
    EvolutionInputs,
    EvolutionProposal,
    EvolutionStrategy,
    EvolutionStrategyId,
)


class NoChangeEvolutionStrategy:
    """Baseline strategy that explicitly proposes no evolution."""

    _STRATEGY_ID = EvolutionStrategyId(name="baseline.no_change", version="1.0.0")

    @property
    def strategy_id(self) -> EvolutionStrategyId:
        """Return the stable baseline strategy identity.

        Returns:
            Baseline name and behavior version.
        """

        return self._STRATEGY_ID

    def propose(self, inputs: EvolutionInputs) -> EvolutionProposal:
        """Return a versioned no-change proposal for the supplied scope.

        Args:
            inputs:
                Validated snapshots and eligible conversation evidence.

        Returns:
            Empty detached proposal with baseline provenance.
        """

        return EvolutionProposal(strategy=self.strategy_id, scope=inputs.scope)


class EvolutionEvaluator:
    """Invoke a replaceable strategy and enforce seam-level provenance."""

    def __init__(self, strategy: EvolutionStrategy) -> None:
        """Initialize the evaluator with a replaceable strategy.

        Args:
            strategy:
                Evolution proposal implementation.
        """

        self._strategy = strategy

    def evaluate(self, inputs: EvolutionInputs) -> EvolutionProposal:
        """Evaluate inputs and reject foreign provenance or evidence references.

        This validates only the strategy seam. Future relationship transitions and
        durable state changes still require established domain validation.

        Args:
            inputs:
                Immutable scoped snapshots and eligible evidence.

        Returns:
            Detached, provenance-checked proposal.

        Raises:
            ValueError:
                If the strategy mislabels its result or cites ineligible evidence.
        """

        proposal = self._strategy.propose(inputs)
        if proposal.strategy != self._strategy.strategy_id:
            raise ValueError("Evolution proposal strategy provenance is invalid.")
        if proposal.scope != inputs.scope:
            raise ValueError("Evolution proposal scope does not match its inputs.")

        eligible = {
            EvolutionEvidenceReference(
                user_message_id=turn.user.id,
                persona_message_id=turn.persona.id,
            )
            for turn in inputs.evidence
        }
        cited = {
            source
            for change in proposal.persona_adaptations
            for source in change.sources
        }
        cited.update(
            source
            for change in proposal.relationship_changes
            for source in change.sources
        )
        if not cited.issubset(eligible):
            raise ValueError("Evolution proposal cites ineligible evidence.")

        return proposal
