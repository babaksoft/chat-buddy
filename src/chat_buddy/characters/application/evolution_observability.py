"""Default behavior for optional evolution observability."""

from __future__ import annotations

from contextlib import nullcontext

from chat_buddy.characters.domain import (
    EvolutionConfiguration,
    EvolutionCorrectionAction,
    EvolutionDecisionOutcome,
    EvolutionEffectState,
    EvolutionOperation,
    EvolutionRebuildReason,
    EvolutionRejectionReason,
    EvolutionSpanAttributes,
)


class NoOpEvolutionObserver:
    """Discard evolution telemetry while preserving identical application behavior."""

    def span(
        self,
        operation: EvolutionOperation,
        attributes: EvolutionSpanAttributes,
    ) -> nullcontext[None]:
        """Return an inert trace scope.

        Args:
            operation:
                Ignored stable operation.
            attributes:
                Ignored safe attributes.

        Returns:
            Inert context manager.
        """

        return nullcontext()

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
        """Discard one terminal effect observation.

        Args:
            state:
                Ignored durable state.
            outcome:
                Ignored decision outcome.
            reason:
                Ignored rejection reason.
            command_count:
                Ignored command count.
            configuration:
                Ignored versioned configuration.
            snapshot_seconds:
                Ignored selector duration.
            strategy_seconds:
                Ignored strategy duration.
        """

    def duplicate_reservation(self) -> None:
        """Discard a duplicate-reservation observation."""

    def projection_rebuilt(
        self,
        reason: EvolutionRebuildReason,
        duration_seconds: float,
        correction_count: int,
    ) -> None:
        """Discard one projection replay observation.

        Args:
            reason:
                Ignored replay trigger.
            duration_seconds:
                Ignored replay duration.
            correction_count:
                Ignored correction count.
        """

    def correction_appended(self, action: EvolutionCorrectionAction) -> None:
        """Discard one correction observation.

        Args:
            action:
                Ignored correction operation.
        """
