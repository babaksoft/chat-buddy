"""End-to-end acceptance of Stage 7 relationship and persona evolution."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import (
    ContinuityService,
    NoChangeEvolutionStrategy,
)
from chat_buddy.characters.domain import EvolutionScope
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbEvolutionRepository,
    DbPersonaRepository,
)
from evaluations.characters import (
    BaselineEvolutionEvaluationPolicy,
    EvolutionEvaluationRunner,
    load_scenarios,
)
from evaluations.characters.policies import NoChangeEvaluationPolicy
from tests.characters_support import start
from tests.evaluations.test_characters_evolution_harness import (
    DATASET,
    DatasetFixtureStrategy,
)
from tests.integration.characters.test_evolution_effect_processing import (
    test_failed_evolution_stays_retryable_without_losing_response as _prove_failed_effect_retry,
)
from tests.integration.characters.test_evolution_projection_replay import (
    test_branch_replay_deactivates_and_restores_relationship_and_adaptation_events as _prove_branch_replay,
)
from tests.integration.characters.test_evolution_projection_replay import (
    test_deleted_projection_caches_rebuild_to_the_same_state as _prove_restart_replay,
)
from tests.integration.characters.test_evolution_projection_replay import (
    test_replacement_updates_persona_adaptation_without_editing_inference as _prove_user_correction,
)
from tests.integration.characters.test_storyline_forks import (
    test_fork_replays_only_copied_evolution_and_remaps_corrections as _prove_storyline_fork,
)


def test_stage_seven_milestone(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Prove explainable evolution, recovery, branching, and isolation end to end.

    Args:
        characters_session_factory:
            Isolated Characters database sessions.
    """

    prove_stage_seven_milestone(characters_session_factory)


def prove_stage_seven_milestone(factory: sessionmaker[Session]) -> None:
    """Exercise the complete Stage 7 milestone through deterministic seams.

    The curated strategy comparison establishes proposal and policy behavior. The
    persisted steps then prove that accepted evolution remains recoverable and
    correct across every graph and continuity lifecycle operation in the slice.

    Args:
        factory:
            SQLite or disposable PostgreSQL Characters sessions.
    """

    _prove_strategy_and_policy_promotion_gates()
    _prove_failed_effect_retry(factory)
    _prove_user_correction(factory)
    _prove_restart_replay(factory)
    _prove_branch_replay(factory)
    _prove_storyline_fork(factory)
    _prove_archive_and_fresh_continuity_isolation(factory)


def _prove_strategy_and_policy_promotion_gates() -> None:
    """Compare strategies and require every curated Stage 7 behavior to pass."""

    scenarios = load_scenarios(DATASET)
    tags = {tag for scenario in scenarios for tag in scenario.tags}
    assert tags >= {
        "adaptation",
        "boundary",
        "branch",
        "correction",
        "fresh_continuity",
        "friendship",
        "hard_invariant",
        "milestone",
        "persona_core",
        "platonic",
        "replay",
        "retry",
        "romance",
        "trust",
    }
    assert {scenario.relationship_intent.value for scenario in scenarios} >= {
        "let_it_develop_naturally",
        "platonic",
    }

    runner = EvolutionEvaluationRunner()
    no_change = runner.run(
        scenarios,
        NoChangeEvolutionStrategy(),
        NoChangeEvaluationPolicy(),
    )
    candidate = runner.run(
        scenarios,
        DatasetFixtureStrategy(scenarios),
        BaselineEvolutionEvaluationPolicy(),
    )

    assert no_change.metrics.pass_rate < candidate.metrics.pass_rate
    assert candidate.metrics.pass_rate == 1.0
    assert candidate.metrics.hard_invariant_violation_rate == 0.0
    assert candidate.metrics.projection_replay_correctness == 1.0
    assert candidate.metrics.branch_fork_correctness == 1.0
    assert candidate.metrics.correction_correctness == 1.0
    assert candidate.metrics.duplicate_effect_rate == 0.0


def _prove_archive_and_fresh_continuity_isolation(
    factory: sessionmaker[Session],
) -> None:
    """Keep archived state immutable and a fresh continuity projection-free.

    Args:
        factory:
            Characters database sessions shared by the acceptance journey.
    """

    archived = start(factory, definition="A patient guide with an immutable core.")
    persona_before = DbPersonaRepository(factory).get(archived.persona_id)
    ContinuityService(DbContinuityRepository(factory)).archive(
        archived.identity_id,
        archived.persona_id,
        archived.continuity_id,
    )
    persona_after = DbPersonaRepository(factory).get(archived.persona_id)
    assert persona_after.core == persona_before.core

    fresh = start(factory, definition="A distinct guide with a fresh continuity.")
    assert fresh.continuity_id != archived.continuity_id
    assert fresh.persona_id != archived.persona_id
    fresh_scope = EvolutionScope(
        identity_id=fresh.identity_id,
        persona_id=fresh.persona_id,
        continuity_id=fresh.continuity_id,
    )
    archived_scope = EvolutionScope(
        identity_id=archived.identity_id,
        persona_id=archived.persona_id,
        continuity_id=archived.continuity_id,
    )
    evolution = DbEvolutionRepository(factory)
    assert evolution.list_events(archived_scope) == ()
    assert evolution.list_events(fresh_scope) == ()
