"""Privacy-safe evolution observability adapter coverage."""

import logging
from collections.abc import Mapping
from contextlib import AbstractContextManager, nullcontext

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from chat_buddy.characters.application import BASELINE_EVOLUTION_CONFIGURATION
from chat_buddy.characters.domain import (
    EvolutionCorrectionAction,
    EvolutionDecisionOutcome,
    EvolutionEffectState,
    EvolutionOperation,
    EvolutionRebuildReason,
    EvolutionRejectionReason,
)
from chat_buddy.characters.infrastructure import (
    LoggingMetricsEvolutionObserver,
)


class RecordingTracer:
    """Capture safe span names and attributes without an exporter."""

    def __init__(self) -> None:
        """Initialize empty span observations."""

        self.calls: list[tuple[str, dict[str, str | int | float | bool]]] = []

    def start_as_current_span(
        self,
        name: str,
        *,
        attributes: Mapping[str, str | int | float | bool],
    ) -> AbstractContextManager[object]:
        """Record and open an inert span.

        Args:
            name:
                Stable span name.
            attributes:
                Safe span attributes.

        Returns:
            Inert span context.
        """

        self.calls.append((name, dict(attributes)))
        return nullcontext()


def test_observer_emits_bounded_metrics_logs_and_spans(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Record lifecycle telemetry without continuity or conversation content."""

    registry = CollectorRegistry()
    tracer = RecordingTracer()
    observer = LoggingMetricsEvolutionObserver(registry, tracer)
    caplog.set_level(logging.INFO)

    with observer.span(
        EvolutionOperation.STRATEGY,
        {"evolution.strategy": "baseline.no_change@1.0.0"},
    ):
        pass
    observer.effect_terminal(
        EvolutionEffectState.REJECTED,
        EvolutionDecisionOutcome.REJECTED,
        EvolutionRejectionReason.USER_BOUNDARY,
        2,
        BASELINE_EVOLUTION_CONFIGURATION,
        0.01,
        0.02,
    )
    observer.projection_rebuilt(EvolutionRebuildReason.BRANCH, 0.03, 1)
    observer.correction_appended(EvolutionCorrectionAction.EXCLUDE)
    observer.duplicate_reservation()

    payload = generate_latest(registry).decode()
    assert "chat_buddy_characters_evolution_effects_total" in payload
    assert 'reason="user_boundary"' in payload
    assert 'phase="snapshot"' in payload
    assert 'reason="branch"' in payload
    assert 'action="exclude"' in payload
    assert "chat_buddy_characters_evolution_duplicate_reservations_total 1.0" in payload
    assert tracer.calls == [
        (
            "characters.evolution.strategy",
            {"evolution.strategy": "baseline.no_change@1.0.0"},
        )
    ]
    assert all(
        not hasattr(record, field)
        for record in caplog.records
        for field in ("conversation_text", "persona_details", "continuity_id")
    )
