"""Policies for exercising native evolution evaluation scenarios."""

from chat_buddy.characters.application import (
    EvolutionProposalValidator,
    StrictBaselineEvolutionThresholdPolicy,
)
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


class BaselineEvolutionEvaluationPolicy:
    """Expose production proposal validation through the evaluation seam."""

    def __init__(self) -> None:
        """Create the strict baseline validator without external dependencies."""

        self._validator = EvolutionProposalValidator(
            StrictBaselineEvolutionThresholdPolicy()
        )

    def evaluate(
        self, snapshot: EvolutionSnapshot, proposal: EvolutionProposal
    ) -> PolicyEvaluation:
        """Validate one scenario proposal and return portable replay output.

        Args:
            snapshot:
                Immutable evaluation state and evidence.
            proposal:
                Candidate typed strategy output.

        Returns:
            Deterministic decision and resulting projections.
        """

        result = self._validator.evaluate(snapshot, proposal)
        return PolicyEvaluation(
            decision=result.decision,
            relationship=result.relationship,
            persona_adaptations=result.persona_adaptations,
        )
