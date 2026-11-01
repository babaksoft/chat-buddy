"""Low-cardinality observability contracts for Characters evolution."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from enum import StrEnum
from typing import Protocol

from chat_buddy.characters.domain.evolution import (
    EvolutionConfiguration,
    EvolutionCorrectionAction,
    EvolutionDecisionOutcome,
    EvolutionEffectState,
    EvolutionRejectionReason,
)

EvolutionSpanAttributes = Mapping[str, str | int | float | bool]


class EvolutionOperation(StrEnum):
    """Bounded evolution operations that may be traced.

    Attributes:
        SELECTOR:
            Immutable evidence selection.
        STRATEGY:
            Typed proposal generation.
        VALIDATION:
            Hard-invariant and policy validation.
        APPLICATION:
            Terminal effect persistence.
    """

    SELECTOR = "selector"
    STRATEGY = "strategy"
    VALIDATION = "validation"
    APPLICATION = "application"


class EvolutionRebuildReason(StrEnum):
    """Bounded reasons for replaying evolution projections.

    Attributes:
        RECOVERY:
            Explicit cache recovery or restart replay.
        PATH_SELECTION:
            Retry-alternative or saved-future selection.
        BRANCH:
            In-place branch selection.
        RESPONSE_COMPLETION:
            Reconciliation before processing a completed response.
        CORRECTION:
            Replay caused by a user-authored correction.
    """

    RECOVERY = "recovery"
    PATH_SELECTION = "path_selection"
    BRANCH = "branch"
    RESPONSE_COMPLETION = "response_completion"
    CORRECTION = "correction"


class EvolutionObserver(Protocol):
    """Optional sink for safe evolution logs, metrics, and trace spans."""

    def span(
        self,
        operation: EvolutionOperation,
        attributes: EvolutionSpanAttributes,
    ) -> AbstractContextManager[object]:
        """Open one lifecycle span.

        Args:
            operation:
                Stable operation name.
            attributes:
                Low-cardinality version and outcome attributes.

        Returns:
            Context manager ending the span on exit.
        """

        ...

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
        """Record one terminal durable effect.

        Args:
            state:
                Durable effect terminal state.
            outcome:
                Application decision outcome.
            reason:
                Stable rejection reason when rejected.
            command_count:
                Number of bounded proposal commands.
            configuration:
                Exact versioned experimental configuration.
            snapshot_seconds:
                Snapshot selection duration.
            strategy_seconds:
                Proposal strategy duration.
        """

        ...

    def duplicate_reservation(self) -> None:
        """Record a repeated reservation resolved by an existing effect."""

        ...

    def projection_rebuilt(
        self,
        reason: EvolutionRebuildReason,
        duration_seconds: float,
        correction_count: int,
    ) -> None:
        """Record one successful projection replay.

        Args:
            reason:
                Stable replay trigger.
            duration_seconds:
                Complete replay and persistence duration.
            correction_count:
                Number of authored corrections included in replay.
        """

        ...

    def correction_appended(self, action: EvolutionCorrectionAction) -> None:
        """Record one successfully appended user correction.

        Args:
            action:
                Stable correction operation.
        """

        ...
