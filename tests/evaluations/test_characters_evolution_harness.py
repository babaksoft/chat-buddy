"""Deterministic Characters evolution evaluation harness tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid5

import pytest
from pydantic import TypeAdapter, ValidationError

from chat_buddy.characters.application import NoChangeEvolutionStrategy
from chat_buddy.characters.domain import (
    EvolutionCommand,
    EvolutionDecision,
    EvolutionDecisionOutcome,
    EvolutionEvent,
    EvolutionProposal,
    EvolutionProvenance,
    EvolutionSnapshot,
    PersonaAdaptation,
    PersonaAdaptationProjection,
    RelationshipProjection,
    StrategyIdentity,
)
from evaluations.characters import (
    EvolutionEvaluationRunner,
    EvolutionScenario,
    PolicyEvaluation,
    load_scenarios,
)
from evaluations.characters.models import CommandExpectation
from evaluations.characters.policies import NoChangeEvaluationPolicy

DATASET = (
    Path(__file__).parents[2] / "evaluations" / "characters" / "datasets" / "v1.jsonl"
)


class DatasetFixtureStrategy:
    """Deterministic test strategy driven by curated command expectations."""

    def __init__(self, scenarios: tuple[EvolutionScenario, ...]) -> None:
        """Index scenarios by their deterministic continuity identifier.

        Args:
            scenarios:
                Curated scenarios to reproduce.
        """

        self.strategy_id = StrategyIdentity(
            name="test.dataset_fixture", version="1.0.0"
        )
        self._scenarios = {
            scenario.build_snapshot().scope.continuity_id: scenario
            for scenario in scenarios
        }

    def propose(self, snapshot: EvolutionSnapshot) -> EvolutionProposal:
        """Return required commands and adversarial commands meant for rejection.

        Args:
            snapshot:
                Immutable scenario snapshot.

        Returns:
            Typed, evidence-backed fixture proposal.
        """

        scenario = self._scenarios[snapshot.scope.continuity_id]
        expectations = scenario.required_proposals
        if scenario.expected_outcome == EvolutionDecisionOutcome.REJECTED:
            expectations += scenario.forbidden_proposals
        return EvolutionProposal(
            id=uuid5(snapshot.scope.continuity_id, "proposal"),
            scope=snapshot.scope,
            expected_relationship_revision=snapshot.relationship.revision,
            expected_adaptation_revision=snapshot.persona_adaptations.revision,
            source=snapshot.source,
            provenance=EvolutionProvenance(
                selector=StrategyIdentity(name="test.selector", version="1.0.0"),
                strategy=self.strategy_id,
                policy=StrategyIdentity(name="test.policy", version="1.0.0"),
                schema_identity=StrategyIdentity(name="test.schema", version="1.0.0"),
            ),
            commands=tuple(
                _build_command(expectation, snapshot) for expectation in expectations
            ),
        )


class DatasetFixturePolicy:
    """Deterministic test policy returning curated decisions and projections."""

    def __init__(self, scenarios: tuple[EvolutionScenario, ...]) -> None:
        """Index expected outcomes by deterministic continuity identifier.

        Args:
            scenarios:
                Curated scenarios to replay.
        """

        self._scenarios = {
            scenario.build_snapshot().scope.continuity_id: scenario
            for scenario in scenarios
        }

    def evaluate(
        self, snapshot: EvolutionSnapshot, proposal: EvolutionProposal
    ) -> PolicyEvaluation:
        """Return the scenario's expected atomic outcome and replay state.

        Args:
            snapshot:
                Immutable starting state.
            proposal:
                Fixture strategy proposal.

        Returns:
            Typed decision and expected replay projections.
        """

        scenario = self._scenarios[snapshot.scope.continuity_id]
        events: tuple[EvolutionEvent, ...] = ()
        if scenario.expected_outcome == EvolutionDecisionOutcome.APPLIED:
            events = tuple(
                EvolutionEvent(
                    id=uuid5(proposal.id, f"event:{index}"),
                    proposal_id=proposal.id,
                    scope=snapshot.scope,
                    command=command,
                    relationship_revision=scenario.expected_relationship.revision,
                    adaptation_revision=0,
                    provenance=proposal.provenance,
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
                for index, command in enumerate(proposal.commands)
            )
        return PolicyEvaluation(
            decision=EvolutionDecision(
                proposal_id=proposal.id,
                outcome=scenario.expected_outcome,
                reason=scenario.expected_reason,
                events=events,
            ),
            relationship=RelationshipProjection(
                scope=snapshot.scope,
                **scenario.expected_relationship.model_dump(),
            ),
            persona_adaptations=PersonaAdaptationProjection(
                scope=snapshot.scope,
                revision=0,
                adaptations=tuple(
                    PersonaAdaptation(**item.model_dump())
                    for item in scenario.expected_adaptations
                ),
            ),
        )


def test_curated_dataset_loads_all_planned_behavioral_scenarios() -> None:
    """Validate the versioned inventory and its required behavioral coverage."""

    scenarios = load_scenarios(DATASET)
    tags = {tag for scenario in scenarios for tag in scenario.tags}
    assert len(scenarios) == 11
    assert {scenario.dataset_version for scenario in scenarios} == {"1.0.0"}
    assert {
        "platonic",
        "gradual",
        "milestone",
        "conflict",
        "boundary",
        "persona_core",
        "classification",
        "retry",
        "correction",
        "fresh_continuity",
    }.issubset(tags)


def test_loader_rejects_invalid_and_mixed_dataset_records(tmp_path: Path) -> None:
    """Fail malformed JSONL values and incompatible dataset versions."""

    invalid = tmp_path / "invalid.jsonl"
    invalid.write_text(
        json.dumps(
            {
                "dataset_version": "1.0.0",
                "name": "invalid",
                "tags": ["test"],
                "relationship_intent": "platonic",
                "evidence": [{"user": "Hello", "persona": "Hello"}],
                "expected_outcome": "rejected",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="require a reason"):
        load_scenarios(invalid)

    mixed = tmp_path / "mixed.jsonl"
    record = json.loads(DATASET.read_text(encoding="utf-8").splitlines()[0])
    record["dataset_version"] = "2.0.0"
    mixed.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValidationError, match="literal_error"):
        load_scenarios(mixed)


def test_runner_compares_no_change_and_fixture_strategies_on_one_dataset() -> None:
    """Compare strategies with identical validated inputs and metric semantics."""

    scenarios = load_scenarios(DATASET)
    runner = EvolutionEvaluationRunner()
    baseline = runner.run(
        scenarios, NoChangeEvolutionStrategy(), NoChangeEvaluationPolicy()
    )
    fixture = runner.run(
        scenarios, DatasetFixtureStrategy(scenarios), DatasetFixturePolicy(scenarios)
    )

    assert baseline.metrics.scenario_count == fixture.metrics.scenario_count == 11
    assert baseline.metrics.passed_count == 3
    assert fixture.metrics.passed_count == 11
    assert fixture.metrics.pass_rate == 1.0
    assert fixture.metrics.schema_validity == 1.0
    assert fixture.metrics.ownership_evidence_validity == 1.0
    assert fixture.metrics.required_proposal_recall == 1.0
    assert fixture.metrics.hard_invariant_violation_rate == 0.0
    assert fixture.metrics.projection_replay_correctness == 1.0
    assert fixture.metrics.branch_fork_correctness == 1.0
    assert fixture.metrics.correction_correctness == 1.0
    assert fixture.metrics.duplicate_effect_rate == 0.0
    assert fixture.metrics.state_oscillation_correctness == 1.0


def test_run_serializes_complete_machine_readable_results() -> None:
    """Emit stable JSON containing aggregate and per-scenario metrics."""

    scenarios = load_scenarios(DATASET)
    run = EvolutionEvaluationRunner().run(
        scenarios, DatasetFixtureStrategy(scenarios), DatasetFixturePolicy(scenarios)
    )
    payload = json.loads(run.model_dump_json())
    assert payload["dataset_version"] == "1.0.0"
    assert payload["strategy"] == "test.dataset_fixture@1.0.0"
    assert payload["metrics"]["passed_count"] == 11
    assert len(payload["results"]) == 11


def _build_command(
    expectation: CommandExpectation, snapshot: EvolutionSnapshot
) -> EvolutionCommand:
    """Turn a portable expectation into its typed domain command.

    Args:
        expectation:
            Rationale-independent command signature.
        snapshot:
            Snapshot supplying exact evidence references.

    Returns:
        One typed evolution command.
    """

    common = {
        "rationale": "Deterministic evaluation fixture.",
        "sources": tuple(
            snapshot.evidence[position - 1].reference
            for position in expectation.evidence
        ),
    }
    values = expectation.model_dump(exclude={"kind", "evidence"}, exclude_none=True)
    return TypeAdapter(EvolutionCommand).validate_python(
        {"kind": expectation.kind, **common, **values}
    )
