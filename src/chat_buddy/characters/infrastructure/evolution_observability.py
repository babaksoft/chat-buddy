"""Structured logging, Prometheus metrics, and optional Phoenix tracing."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import AbstractContextManager, nullcontext
from functools import lru_cache
from typing import Protocol

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Histogram

from chat_buddy.characters.domain import (
    EvolutionConfiguration,
    EvolutionCorrectionAction,
    EvolutionDecisionOutcome,
    EvolutionEffectState,
    EvolutionOperation,
    EvolutionRebuildReason,
    EvolutionRejectionReason,
    EvolutionSpanAttributes,
    StrategyIdentity,
)

logger = logging.getLogger(__name__)


class _EvolutionTracer(Protocol):
    """Minimal OpenTelemetry-compatible tracer contract."""

    def start_as_current_span(
        self,
        name: str,
        *,
        attributes: Mapping[str, str | int | float | bool],
    ) -> AbstractContextManager[object]:
        """Start a trace span.

        Args:
            name:
                Stable span name.
            attributes:
                Safe low-cardinality span attributes.

        Returns:
            Active span context manager.
        """

        ...


class LoggingMetricsEvolutionObserver:
    """Emit privacy-safe structured logs and bounded Prometheus metrics."""

    def __init__(
        self,
        registry: CollectorRegistry = REGISTRY,
        tracer: _EvolutionTracer | None = None,
    ) -> None:
        """Create isolated collectors and an optional trace sink.

        Args:
            registry:
                Prometheus collector registry receiving evolution metrics.
            tracer:
                Optional OpenTelemetry-compatible tracer, including Phoenix.
        """

        self._tracer = tracer
        version_labels = ("selector", "strategy", "policy")
        self._effects = Counter(
            "chat_buddy_characters_evolution_effects_total",
            "Terminal Characters evolution effects.",
            (*version_labels, "state", "outcome", "reason"),
            registry=registry,
        )
        self._commands = Histogram(
            "chat_buddy_characters_evolution_proposal_commands",
            "Commands in a terminal evolution proposal.",
            version_labels,
            buckets=(0, 1, 2, 3, 4, 5, 8),
            registry=registry,
        )
        self._latency = Histogram(
            "chat_buddy_characters_evolution_phase_seconds",
            "Evolution selector and strategy latency.",
            (*version_labels, "phase"),
            registry=registry,
        )
        self._rebuilds = Histogram(
            "chat_buddy_characters_evolution_projection_rebuild_seconds",
            "Evolution projection rebuild duration.",
            ("reason",),
            registry=registry,
        )
        self._corrections = Counter(
            "chat_buddy_characters_evolution_corrections_total",
            "Successfully appended evolution corrections.",
            ("action",),
            registry=registry,
        )
        self._duplicates = Counter(
            "chat_buddy_characters_evolution_duplicate_reservations_total",
            "Evolution reservations resolved by an existing effect.",
            registry=registry,
        )

    def span(
        self,
        operation: EvolutionOperation,
        attributes: EvolutionSpanAttributes,
    ) -> AbstractContextManager[object]:
        """Open an optional Phoenix or OpenTelemetry trace span.

        Args:
            operation:
                Stable operation name.
            attributes:
                Privacy-safe span attributes.

        Returns:
            Active or inert context manager.
        """

        if self._tracer is None:
            return nullcontext()
        return self._tracer.start_as_current_span(
            f"characters.evolution.{operation.value}", attributes=attributes
        )

    def effect_terminal(
        self,
        state: EvolutionEffectState,
        outcome: EvolutionDecisionOutcome,
        reason: EvolutionRejectionReason | None,
        command_count: int,
        configuration: EvolutionConfiguration,
        snapshot_seconds: float,
        strategy_seconds: float,
    ) -> None:
        """Emit terminal effect logs, counts, command size, and latency.

        Args:
            state:
                Durable terminal state.
            outcome:
                Application decision outcome.
            reason:
                Stable rejection reason when rejected.
            command_count:
                Number of proposal commands.
            configuration:
                Exact versioned configuration.
            snapshot_seconds:
                Selector duration.
            strategy_seconds:
                Strategy duration.
        """

        versions = _version_labels(configuration)
        reason_value = reason.value if reason is not None else "none"
        self._effects.labels(*versions, state.value, outcome.value, reason_value).inc()
        self._commands.labels(*versions).observe(command_count)
        self._latency.labels(*versions, "snapshot").observe(snapshot_seconds)
        self._latency.labels(*versions, "strategy").observe(strategy_seconds)
        logger.info(
            "Characters evolution effect reached a terminal state.",
            extra={
                "evolution_state": state.value,
                "evolution_outcome": outcome.value,
                "evolution_reason": reason_value,
                "evolution_command_count": command_count,
                "evolution_selector": versions[0],
                "evolution_strategy": versions[1],
                "evolution_policy": versions[2],
                "evolution_schema": _identity(configuration.schema_identity),
                "evolution_provider": configuration.provider or "none",
                "evolution_model": configuration.model or "none",
                "evolution_snapshot_seconds": snapshot_seconds,
                "evolution_strategy_seconds": strategy_seconds,
            },
        )

    def duplicate_reservation(self) -> None:
        """Count a reservation resolved by an existing effect."""

        self._duplicates.inc()
        logger.info("Characters evolution reused an existing effect reservation.")

    def projection_rebuilt(
        self,
        reason: EvolutionRebuildReason,
        duration_seconds: float,
        correction_count: int,
    ) -> None:
        """Emit projection replay duration, reason, and correction count.

        Args:
            reason:
                Stable replay trigger.
            duration_seconds:
                Replay and persistence duration.
            correction_count:
                Authored corrections included in replay.
        """

        self._rebuilds.labels(reason.value).observe(duration_seconds)
        logger.info(
            "Characters evolution projections rebuilt.",
            extra={
                "evolution_rebuild_reason": reason.value,
                "evolution_rebuild_seconds": duration_seconds,
                "evolution_correction_count": correction_count,
            },
        )

    def correction_appended(self, action: EvolutionCorrectionAction) -> None:
        """Count one successfully appended correction.

        Args:
            action:
                Stable correction operation.
        """

        self._corrections.labels(action.value).inc()
        logger.info(
            "Characters evolution correction appended.",
            extra={"evolution_correction_action": action.value},
        )


@lru_cache(maxsize=1)
def default_evolution_observer() -> LoggingMetricsEvolutionObserver:
    """Return the process-wide default metrics observer.

    Returns:
        Shared observer backed by the default Prometheus registry.
    """

    return LoggingMetricsEvolutionObserver()


def create_phoenix_evolution_observer(
    endpoint: str,
    project_name: str = "chat-buddy-characters-evolution",
) -> LoggingMetricsEvolutionObserver:
    """Create an explicitly enabled observer exporting spans to Phoenix.

    Args:
        endpoint:
            Phoenix OTLP endpoint.
        project_name:
            Phoenix project receiving the spans.

    Returns:
        Metrics observer with a Phoenix-backed tracer.
    """

    from phoenix.otel import register

    provider = register(
        endpoint=endpoint,
        project_name=project_name,
        batch=True,
        set_global_tracer_provider=False,
        verbose=False,
    )
    tracer = provider.get_tracer("chat_buddy.characters.evolution")
    return LoggingMetricsEvolutionObserver(tracer=tracer)


def _version_labels(configuration: EvolutionConfiguration) -> tuple[str, str, str]:
    """Return bounded selector, strategy, and policy labels.

    Args:
        configuration:
            Exact versioned evolution configuration.

    Returns:
        Stable Prometheus label values.
    """

    return (
        _identity(configuration.selector),
        _identity(configuration.strategy),
        _identity(configuration.threshold_policy),
    )


def _identity(identity: StrategyIdentity) -> str:
    """Render one strategy identity without accepting free-form content.

    Args:
        identity:
            Validated bounded strategy identity.

    Returns:
        Stable name and semantic version label.
    """

    return f"{identity.name}@{identity.version}"
