"""Minimal policies for exercising the native runner itself."""

from chat_buddy.characters.domain import (
    EvolutionDecision,
    EvolutionDecisionOutcome,
    EvolutionProposal,
    EvolutionSnapshot,
)
from evaluations.characters.models import PolicyEvaluation


class NoChangeEvaluationPolicy:
    """Resolve an empty proposal without interpreting relationship transitions."""

    def evaluate(
        self, snapshot: EvolutionSnapshot, proposal: EvolutionProposal
    ) -> PolicyEvaluation:
        """Return unchanged projections for an empty proposal.

        Args:
            snapshot:
                Immutable evaluation state.
            proposal:
                Typed proposal from the no-change strategy.

        Returns:
            No-change decision and original projections.

        Raises:
            ValueError:
                If paired with a strategy that proposes commands.
        """

        if proposal.commands:
            raise ValueError("NoChangeEvaluationPolicy accepts only empty proposals.")
        return PolicyEvaluation(
            decision=EvolutionDecision(
                proposal_id=proposal.id,
                outcome=EvolutionDecisionOutcome.NO_CHANGE,
            ),
            relationship=snapshot.relationship,
            persona_adaptations=snapshot.persona_adaptations,
        )
