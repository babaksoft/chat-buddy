"""Provider-backed baseline evolution strategy tests."""

from pathlib import Path

import pytest

from chat_buddy.characters.application import (
    BASELINE_EVOLUTION_SCHEMA,
    BASELINE_PROVIDER_EVOLUTION_STRATEGY,
    BaselineEvolutionStrategy,
)
from chat_buddy.characters.domain import (
    EffectiveGeneration,
    EvolutionConfiguration,
    GenerationConfiguration,
    InvalidProviderResponseError,
    ModelDescriptor,
    PromptMessage,
    StrategyIdentity,
)
from evaluations.characters import load_scenarios

DATASET = (
    Path(__file__).parents[3] / "evaluations" / "characters" / "datasets" / "v1.jsonl"
)


class FakeEvolutionGateway:
    """Return one deterministic JSON payload and record invocation inputs."""

    def __init__(self, response: str) -> None:
        """Store the exact response.

        Args:
            response:
                JSON text returned to the strategy.
        """

        self.response = response
        self.calls: list[
            tuple[tuple[PromptMessage, ...], EffectiveGeneration, dict[str, object]]
        ] = []

    def propose_evolution(
        self,
        messages: tuple[PromptMessage, ...],
        generation: EffectiveGeneration,
        schema: dict[str, object],
    ) -> str:
        """Return configured JSON without external access.

        Args:
            messages:
                Complete provider prompt.
            generation:
                Effective evolution generation.
            schema:
                Bounded structured-output schema.

        Returns:
            Configured response.
        """

        self.calls.append((messages, generation, schema))
        return self.response


def _generation() -> EffectiveGeneration:
    """Build one deterministic evolution model selection.

    Returns:
        Effective test generation.
    """

    configuration = GenerationConfiguration(
        max_output_tokens=256, temperature=0, seed=0
    )
    return EffectiveGeneration(
        model=ModelDescriptor(
            provider="fake",
            model="evolution-test",
            context_tokens=4096,
            output_tokens=256,
            capabilities=frozenset({"evolution"}),
            parameters=frozenset({"temperature", "seed"}),
        ),
        configuration=configuration,
        capability="evolution",
        input_tokens=3840,
    )


def _configuration() -> EvolutionConfiguration:
    """Build exact baseline provenance.

    Returns:
        Provider-backed baseline configuration.
    """

    return EvolutionConfiguration(
        selector=StrategyIdentity(name="baseline.exact_evidence", version="1.0.0"),
        strategy=BASELINE_PROVIDER_EVOLUTION_STRATEGY,
        threshold_policy=StrategyIdentity(name="baseline.strict", version="1.0.0"),
        schema_identity=BASELINE_EVOLUTION_SCHEMA,
        provider="fake",
        model="evolution-test",
    )


def test_baseline_returns_typed_bounded_output_with_exact_provenance() -> None:
    """Translate provider positions into authoritative exact evidence."""

    snapshot = load_scenarios(DATASET)[0].build_snapshot()
    gateway = FakeEvolutionGateway(
        """{"commands":[{"kind":"set_affection","rationale":"Two explicit friendship confirmations.","evidence":[1,2],"expected":"neutral","value":"warm"}]}"""
    )
    strategy = BaselineEvolutionStrategy(gateway, _generation(), _configuration())

    proposal = strategy.propose(snapshot)

    assert proposal.provenance == _configuration().provenance()
    assert proposal.commands[0].sources == tuple(
        evidence.reference for evidence in snapshot.evidence
    )
    assert proposal.source in proposal.commands[0].sources
    messages, generation, schema = gateway.calls[0]
    assert generation.capability == "evolution"
    assert schema["additionalProperties"] is False
    assert "new_source" in messages[1].content
    assert "Summary context is never evidence" in messages[0].content


@pytest.mark.parametrize(
    "response",
    [
        '{"commands":[{"kind":"set_affection","rationale":"Old only","evidence":[1],"expected":"neutral","value":"warm"}]}',
        '{"commands":[{"kind":"set_affection","rationale":"Invented","evidence":[99],"expected":"neutral","value":"warm"}]}',
        '{"commands":[{"kind":"set_affection","rationale":"Wrong shape","evidence":[1,2],"value":"warm"}]}',
        "not-json",
    ],
)
def test_baseline_rejects_untrusted_provider_output(response: str) -> None:
    """Reject missing new-source support, invented positions, and invalid syntax.

    Args:
        response:
            Invalid provider response.
    """

    snapshot = load_scenarios(DATASET)[0].build_snapshot()
    strategy = BaselineEvolutionStrategy(
        FakeEvolutionGateway(response), _generation(), _configuration()
    )

    with pytest.raises(InvalidProviderResponseError):
        strategy.propose(snapshot)


def test_baseline_uses_empty_commands_for_no_change() -> None:
    """Preserve a provider's conservative no-change decision."""

    snapshot = load_scenarios(DATASET)[2].build_snapshot()
    proposal = BaselineEvolutionStrategy(
        FakeEvolutionGateway('{"commands":[]}'), _generation(), _configuration()
    ).propose(snapshot)

    assert proposal.commands == ()
