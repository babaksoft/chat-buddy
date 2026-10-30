"""Deterministic runner and metric aggregation for evolution scenarios."""

from __future__ import annotations

from collections.abc import Iterable

from chat_buddy.characters.application import EvolutionEvaluator
from chat_buddy.characters.domain import (
    EvolutionCommand,
    EvolutionDecisionOutcome,
    EvolutionSnapshot,
    EvolutionStrategy,
)
from evaluations.characters.models import (
    AggregateMetrics,
    CommandExpectation,
    EvaluationRun,
    EvolutionEvaluationPolicy,
    EvolutionScenario,
    RelationshipState,
    ScenarioResult,
)


class EvolutionEvaluationRunner:
    """Compare any typed evolution strategy and evaluation policy."""

    def run(
        self,
        scenarios: tuple[EvolutionScenario, ...],
        strategy: EvolutionStrategy,
        policy: EvolutionEvaluationPolicy,
    ) -> EvaluationRun:
        """Evaluate ordered scenarios.

        Args:
            scenarios:
                Validated dataset scenarios.
            strategy:
                Replaceable typed proposal strategy.
            policy:
                Replaceable deterministic validation and replay policy.

        Returns:
            Per-scenario and aggregate machine-readable results.

        Raises:
            ValueError:
                If no scenarios are provided.
        """

        if not scenarios:
            raise ValueError("Evolution evaluation requires at least one scenario.")

        results = tuple(
            self._run_scenario(scenario, strategy, policy) for scenario in scenarios
        )

        return EvaluationRun(
            dataset_version=scenarios[0].dataset_version,
            strategy=f"{strategy.strategy_id.name}@{strategy.strategy_id.version}",
            results=results,
            metrics=_aggregate(results),
        )

    def _run_scenario(
        self,
        scenario: EvolutionScenario,
        strategy: EvolutionStrategy,
        policy: EvolutionEvaluationPolicy,
    ) -> ScenarioResult:
        """Evaluate one scenario and contain strategy or policy failures.

        Args:
            scenario:
                Validated deterministic scenario.
            strategy:
                Proposal strategy under evaluation.
            policy:
                Validation and replay policy under evaluation.

        Returns:
            Stable metrics and optional diagnostic.
        """

        try:
            snapshot = scenario.build_snapshot()
            proposal = EvolutionEvaluator(strategy).evaluate(snapshot)
        except Exception as error:  # noqa: BLE001 - candidate failures are results.
            return _failed_result(scenario, error, ownership=False)

        actual = tuple(
            _command_expectation(command, snapshot) for command in proposal.commands
        )
        required = set(scenario.required_proposals)
        forbidden = set(scenario.forbidden_proposals)
        actual_set = set(actual)
        recall = len(required & actual_set) / len(required) if required else 1.0
        forbidden_count = len(forbidden & actual_set)
        forbidden_rate = forbidden_count / len(actual) if actual else 0.0
        duplicate_rate = (
            (len(actual) - len(actual_set)) / len(actual) if actual else 0.0
        )

        try:
            evaluated = policy.evaluate(snapshot, proposal)
        except Exception as error:  # noqa: BLE001 - policy failures are results.
            return _failed_result(scenario, error, ownership=True)

        decision_correct = (
            evaluated.decision.outcome == scenario.expected_outcome
            and evaluated.decision.reason == scenario.expected_reason
        )
        expected_no_change = (
            scenario.expected_outcome == EvolutionDecisionOutcome.NO_CHANGE
        )
        actual_no_change = (
            evaluated.decision.outcome == EvolutionDecisionOutcome.NO_CHANGE
            and not proposal.commands
        )
        no_change_correct = expected_no_change == actual_no_change
        relationship = RelationshipState.model_validate(
            evaluated.relationship.model_dump(exclude={"scope"})
        )
        adaptations = tuple(
            (item.facet, item.value)
            for item in evaluated.persona_adaptations.adaptations
        )
        expected_adaptations = tuple(
            (item.facet, item.value) for item in scenario.expected_adaptations
        )
        replay_correct = (
            relationship == scenario.expected_relationship
            and adaptations == expected_adaptations
        )
        hard_violations = (
            forbidden_count
            if evaluated.decision.outcome == EvolutionDecisionOutcome.APPLIED
            else 0
        )
        passed = (
            recall == 1.0
            and hard_violations == 0
            and no_change_correct
            and decision_correct
            and replay_correct
            and duplicate_rate == 0.0
        )

        return ScenarioResult(
            name=scenario.name,
            tags=scenario.tags,
            schema_valid=True,
            ownership_evidence_valid=True,
            required_proposal_recall=recall,
            forbidden_proposal_rate=forbidden_rate,
            hard_invariant_violations=hard_violations,
            no_change_correct=no_change_correct,
            policy_decision_correct=decision_correct,
            actual_outcome=evaluated.decision.outcome,
            rejection_reason=evaluated.decision.reason,
            projection_replay_correct=replay_correct,
            duplicate_effect_rate=duplicate_rate,
            passed=passed,
        )


def _command_expectation(
    command: EvolutionCommand, snapshot: EvolutionSnapshot
) -> CommandExpectation:
    """Normalize a typed command.

    Args:
        command:
            Typed evolution command.
        snapshot:
            Snapshot supplying evidence positions.

    Returns:
        Portable command signature.
    """

    references = {
        evidence.reference: index
        for index, evidence in enumerate(snapshot.evidence, start=1)
    }

    return CommandExpectation(
        kind=command.kind,
        expected=getattr(command, "expected", None),
        value=getattr(command, "value", None),
        facet=getattr(command, "facet", None),
        milestone=getattr(command, "milestone", None),
        evidence=tuple(references[source] for source in command.sources),
    )


def _failed_result(
    scenario: EvolutionScenario, error: Exception, *, ownership: bool
) -> ScenarioResult:
    """Create a stable failed result for invalid candidate output.

    Args:
        scenario:
            Scenario that failed.
        error:
            Contained strategy or policy exception.
        ownership:
            Whether strategy seam ownership already passed.

    Returns:
        Failed per-scenario result.
    """

    return ScenarioResult(
        name=scenario.name,
        tags=scenario.tags,
        schema_valid=False,
        ownership_evidence_valid=ownership,
        required_proposal_recall=0.0,
        forbidden_proposal_rate=0.0,
        hard_invariant_violations=1,
        no_change_correct=False,
        policy_decision_correct=False,
        actual_outcome=None,
        rejection_reason=None,
        projection_replay_correct=False,
        duplicate_effect_rate=0.0,
        passed=False,
        error=f"{type(error).__name__}: {error}",
    )


def _aggregate(results: tuple[ScenarioResult, ...]) -> AggregateMetrics:
    """Aggregate deterministic scores over one run.

    Args:
        results:
            Ordered scenario results.

    Returns:
        Aggregate metrics including tagged capability subsets.
    """

    count = len(results)
    return AggregateMetrics(
        scenario_count=count,
        passed_count=sum(result.passed for result in results),
        pass_rate=_mean(result.passed for result in results),
        schema_validity=_mean(result.schema_valid for result in results),
        ownership_evidence_validity=_mean(
            result.ownership_evidence_valid for result in results
        ),
        required_proposal_recall=_mean(
            result.required_proposal_recall for result in results
        ),
        forbidden_proposal_rate=_mean(
            result.forbidden_proposal_rate for result in results
        ),
        hard_invariant_violation_rate=_mean(
            result.hard_invariant_violations > 0 for result in results
        ),
        no_change_correctness=_mean(result.no_change_correct for result in results),
        policy_acceptance_correctness=_mean(
            result.policy_decision_correct for result in results
        ),
        projection_replay_correctness=_mean(
            result.projection_replay_correct for result in results
        ),
        branch_fork_correctness=_tagged_score(results, {"branch", "fork", "retry"}),
        correction_correctness=_tagged_score(results, {"correction"}),
        duplicate_effect_rate=_mean(result.duplicate_effect_rate for result in results),
        state_oscillation_correctness=_tagged_score(results, {"oscillation"}),
    )


def _mean(values: Iterable[bool | float]) -> float:
    """Calculate a mean for a finite metric sequence.

    Args:
        values:
            Boolean or numeric metric values.

    Returns:
        Arithmetic mean, or one for an empty capability subset.
    """

    items = tuple(float(value) for value in values)
    return sum(items) / len(items) if items else 1.0


def _tagged_score(results: tuple[ScenarioResult, ...], tags: set[str]) -> float:
    """Return replay correctness for scenarios matching capability tags.

    Args:
        results:
            Ordered scenario results.
        tags:
            Any matching capability tags.

    Returns:
        Mean tagged replay score, or one when no scenario exercises the capability.
    """

    return _mean(
        result.projection_replay_correct
        for result in results
        if tags.intersection(result.tags)
    )
