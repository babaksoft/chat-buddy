"""Optional Phoenix evolution evaluation reporting coverage."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from chat_buddy.characters.application import NoChangeEvolutionStrategy
from evaluations.characters.models import load_scenarios
from evaluations.characters.phoenix import PhoenixEvolutionEvaluationAdapter
from evaluations.characters.policies import (
    NO_CHANGE_EVALUATION_CONFIGURATION,
    NoChangeEvaluationPolicy,
)
from evaluations.characters.runner import EvolutionEvaluationRunner

DATASET = (
    Path(__file__).parents[2] / "evaluations" / "characters" / "datasets" / "v1.jsonl"
)


def test_phoenix_adapter_publishes_scenarios_runs_and_metrics() -> None:
    """Send exact configuration and deterministic annotations only when invoked."""

    scenarios = load_scenarios(DATASET)
    run = EvolutionEvaluationRunner().run(
        scenarios,
        NoChangeEvolutionStrategy(NO_CHANGE_EVALUATION_CONFIGURATION),
        NoChangeEvaluationPolicy(),
    )
    examples = [
        {"id": f"example-{index}", "input": {"name": scenario.name}}
        for index, scenario in enumerate(scenarios)
    ]
    client = MagicMock()
    client.datasets.create_dataset.return_value = SimpleNamespace(
        id="dataset-id", version_id="version-id", examples=examples
    )
    client.experiments.create.return_value = {"id": "experiment-id"}
    client.experiments.log_run.side_effect = [
        {"id": f"run-{index}"} for index in range(len(scenarios))
    ]

    experiment_id = PhoenixEvolutionEvaluationAdapter(client).publish_and_report(
        "characters-evolution-v1",
        scenarios,
        run,
        NO_CHANGE_EVALUATION_CONFIGURATION,
    )

    assert experiment_id == "experiment-id"
    dataset_call = client.datasets.create_dataset.call_args.kwargs
    assert dataset_call["name"] == "characters-evolution-v1"
    assert len(dataset_call["examples"]) == len(scenarios)
    metadata = client.experiments.create.call_args.kwargs["experiment_metadata"]
    assert metadata["configuration"]["strategy"] == {
        "name": "baseline.no_change",
        "version": "1.0.0",
    }
    assert metadata["configuration"]["selector"] == {
        "name": "evaluation.curated_scenarios",
        "version": "1.0.0",
    }
    assert client.experiments.log_run.call_count == len(scenarios)
    assert client.experiments.log_evaluation.call_count > len(scenarios)
