"""Command-line entry point for native Characters evolution evaluations."""

from __future__ import annotations

import argparse
from pathlib import Path

from chat_buddy.characters.application import NoChangeEvolutionStrategy
from evaluations.characters.models import load_scenarios
from evaluations.characters.phoenix import PhoenixEvolutionEvaluationAdapter
from evaluations.characters.policies import (
    NO_CHANGE_EVALUATION_CONFIGURATION,
    NoChangeEvaluationPolicy,
)
from evaluations.characters.runner import EvolutionEvaluationRunner

DEFAULT_DATASET = Path(__file__).with_name("datasets") / "v1.jsonl"


def main() -> int:
    """Run the no-change baseline and optionally write machine-readable JSON.

    Returns:
        Zero after a completed run; comparison metrics are not a process failure.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--phoenix-endpoint")
    parser.add_argument(
        "--phoenix-dataset", default="chat-buddy-characters-evolution-v1"
    )
    arguments = parser.parse_args()

    scenarios = load_scenarios(arguments.dataset)
    run = EvolutionEvaluationRunner().run(
        scenarios,
        NoChangeEvolutionStrategy(NO_CHANGE_EVALUATION_CONFIGURATION),
        NoChangeEvaluationPolicy(),
    )
    if arguments.json_output is not None:
        arguments.json_output.write_text(
            run.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    if arguments.phoenix_endpoint is not None:
        PhoenixEvolutionEvaluationAdapter.from_endpoint(
            arguments.phoenix_endpoint
        ).publish_and_report(
            arguments.phoenix_dataset,
            scenarios,
            run,
            NO_CHANGE_EVALUATION_CONFIGURATION,
        )

    print(
        f"{run.strategy}: {run.metrics.passed_count}/{run.metrics.scenario_count} "
        f"scenarios passed; required recall "
        f"{run.metrics.required_proposal_recall:.1%}; hard violations "
        f"{run.metrics.hard_invariant_violation_rate:.1%}"
    )
    for result in run.results:
        marker = "PASS" if result.passed else "FAIL"
        print(f"{marker:4} {result.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
