"""Explicit Phoenix publishing for native Characters evolution evaluations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from chat_buddy.characters.domain import EvolutionConfiguration
from evaluations.characters.models import EvaluationRun, EvolutionScenario


class PhoenixClient(Protocol):
    """Narrow client shape used by the optional evaluation adapter."""

    @property
    def datasets(self) -> Any:
        """Return the Phoenix dataset resource.

        Returns:
            Dataset management resource.
        """

        ...

    @property
    def experiments(self) -> Any:
        """Return the Phoenix experiment resource.

        Returns:
            Experiment management resource.
        """

        ...


class PhoenixEvolutionEvaluationAdapter:
    """Publish curated scenarios, runs, and deterministic metrics to Phoenix."""

    def __init__(self, client: PhoenixClient) -> None:
        """Bind an explicitly configured Phoenix client.

        Args:
            client:
                Phoenix-compatible dataset and experiment client.
        """

        self._client = client

    @classmethod
    def from_endpoint(cls, endpoint: str) -> PhoenixEvolutionEvaluationAdapter:
        """Create an adapter for an explicitly selected Phoenix server.

        Args:
            endpoint:
                Phoenix HTTP API base URL.

        Returns:
            Ready optional evaluation adapter.
        """

        from phoenix.client import Client

        return cls(Client(base_url=endpoint))

    def publish_and_report(
        self,
        dataset_name: str,
        scenarios: tuple[EvolutionScenario, ...],
        run: EvaluationRun,
        configuration: EvolutionConfiguration,
    ) -> str:
        """Publish one immutable dataset version and its deterministic run.

        Args:
            dataset_name:
                Stable Phoenix dataset name.
            scenarios:
                Validated curated scenario inputs.
            run:
                Native deterministic evaluation output.
            configuration:
                Exact selector, strategy, policy, schema, provider, and model
                versions evaluated by the run.

        Returns:
            Phoenix experiment identifier.

        Raises:
            ValueError:
                If scenario and result identities do not match.
        """

        result_names = tuple(result.name for result in run.results)
        scenario_names = tuple(scenario.name for scenario in scenarios)
        if scenario_names != result_names:
            raise ValueError("Phoenix reporting requires matching ordered scenarios.")

        dataset = self._client.datasets.create_dataset(
            name=dataset_name,
            examples=tuple(_dataset_example(scenario) for scenario in scenarios),
            dataset_description=(
                "Versioned curated Characters relationship-evolution scenarios."
            ),
        )
        experiment = self._client.experiments.create(
            dataset_id=dataset.id,
            dataset_version_id=dataset.version_id,
            experiment_name=run.strategy,
            experiment_description=(
                "Deterministic local Characters evolution evaluation."
            ),
            experiment_metadata={
                "dataset_version": run.dataset_version,
                "configuration": configuration.model_dump(mode="json"),
                "aggregate_metrics": run.metrics.model_dump(mode="json"),
            },
        )
        experiment_id = str(experiment["id"])
        examples = {
            example["input"]["name"]: example["id"] for example in dataset.examples
        }

        for result in run.results:
            now = datetime.now(UTC)
            recorded = self._client.experiments.log_run(
                experiment_id=experiment_id,
                dataset_example_id=examples[result.name],
                output=result.model_dump(mode="json"),
                start_time=now,
                end_time=now,
            )
            run_id = str(recorded["id"])

            for name, score in _scenario_metrics(result.model_dump(mode="json")):
                self._client.experiments.log_evaluation(
                    experiment_run_id=run_id,
                    name=name,
                    annotator_kind="CODE",
                    score=score,
                )

        return experiment_id


def _dataset_example(scenario: EvolutionScenario) -> dict[str, object]:
    """Convert one curated scenario to Phoenix's portable example shape.

    Args:
        scenario:
            Validated deterministic evaluation scenario.

    Returns:
        JSON-compatible Phoenix dataset example.
    """

    return {
        "input": scenario.model_dump(mode="json"),
        "output": {
            "expected_outcome": scenario.expected_outcome.value,
            "expected_reason": (
                scenario.expected_reason.value
                if scenario.expected_reason is not None
                else None
            ),
        },
        "metadata": {
            "dataset_version": scenario.dataset_version,
            "tags": list(scenario.tags),
        },
    }


def _scenario_metrics(payload: dict[str, object]) -> tuple[tuple[str, float], ...]:
    """Extract deterministic numeric scenario metrics for Phoenix annotations.

    Args:
        payload:
            Serialized native scenario result.

    Returns:
        Stable metric names and numeric scores.
    """

    excluded = {"name", "tags", "actual_outcome", "rejection_reason", "error"}
    metrics: list[tuple[str, float]] = []

    for name, value in payload.items():
        if name in excluded:
            continue

        if isinstance(value, (bool, int, float)):
            metrics.append((name, float(value)))

    return tuple(metrics)
