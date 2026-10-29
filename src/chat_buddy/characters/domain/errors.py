"""Typed validation, operational and management failures."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chat_buddy.characters.domain.branching import BranchDecision


class IdentityNotFoundError(LookupError):
    """The requested identity does not exist."""


class FrozenIdentityError(ValueError):
    """An identity's authored fields can no longer be edited."""


class StaleIdentityError(ValueError):
    """An edit used an outdated identity revision."""


class PersonaNotFoundError(LookupError):
    """The requested persona does not exist."""


class FrozenPersonaError(ValueError):
    """An persona's authored fields can no longer be edited."""


class StalePersonaError(ValueError):
    """An edit used an outdated persona revision."""


class ContinuityNotFoundError(LookupError):
    """No continuity exists within the submitted ownership scope."""


class ActiveContinuityError(ValueError):
    """An active Ongoing continuity already exists for the selected pair."""


class ActiveStorylineError(ValueError):
    """An active Storyline already occupies the selected profile pair."""


class StaleStorylineError(ValueError):
    """A Storyline write used an outdated optimistic revision."""


class LockedSceneSetupError(ValueError):
    """A scene setup is immutable after its first committed user message."""


class IncompleteLatestSceneError(ValueError):
    """The latest scene cannot be followed until its selected turn is complete."""


class InvalidSceneOwnershipError(LookupError):
    """A scene is absent or does not match the supplied complete ownership."""


class StorylineForkConflictError(ValueError):
    """A reviewed fork conflicts with source state or target pair ownership."""


class ConfirmationConflictError(ValueError):
    """A confirmation identifier was reused for different submitted data."""


class UnsupportedContinuityModeError(ValueError):
    """The requested continuity mode cannot yet be started."""


class ArchivedContinuityError(ValueError):
    """An archived continuity cannot accept writes."""


class HistoricalSceneReadOnlyError(ValueError):
    """A nonlatest Storyline scene cannot accept ordinary conversation writes."""


class ModelResolutionError(ValueError):
    """The provider/model selection is not configured."""


class UnsupportedGenerationError(ValueError):
    """A capability, parameter, or output reserve is unsupported."""


class ProviderInvocationError(RuntimeError):
    """A provider failed; the message contains no provider payload or secrets."""


class InvalidProviderResponseError(ProviderInvocationError):
    """A provider returned malformed or empty utility output."""


class ConversationNotFoundError(LookupError):
    """The conversation or attempt does not match the supplied ownership."""


class IncompleteTurnError(ValueError):
    """An unmatched user tail must be continued before sending again."""


class AttemptConflictError(ValueError):
    """An open, terminal, or stale attempt prevents the requested operation."""


class ContextCapacityError(ValueError):
    """Required prompt context cannot be represented within input capacity."""


class SummaryConflictError(ValueError):
    """A summary replacement used stale lineage or an invalid checkpoint."""


class MemoryNotFoundError(LookupError):
    """No logical memory exists within the supplied Storyline ownership."""


class InvalidMemoryDeltaTargetError(ValueError):
    """An extraction delta cites an omitted, foreign, stale, or invented target."""


class StaleMemoryRevisionError(ValueError):
    """A memory lifecycle command used an outdated current revision."""


class ProtectedMemoryCorrectionError(ValueError):
    """Automatic extraction attempted to supersede user-authored content."""


class MemorySubjectConflictError(ValueError):
    """A current logical memory already owns the normalized subject."""


class MemoryConflictNotFoundError(LookupError):
    """No extraction conflict exists within the supplied Storyline ownership."""


class StaleMemoryConflictError(ValueError):
    """A conflict dismissal no longer matches the current memory revision."""


class InvalidTemporalProvenanceError(ValueError):
    """Memory occurrence, learning, or source provenance is inconsistent."""


class ExtractionEffectConflictError(ValueError):
    """An extraction effect is terminal, ineligible, or reserved inconsistently."""


class EvolutionEffectConflictError(ValueError):
    """An evolution effect is terminal or reserved with different audit data."""


class EvolutionProjectionConflictError(ValueError):
    """Evolution projections are absent, foreign, or changed concurrently."""


class InvalidParentError(ValueError):
    """A message parent is absent, foreign, cyclic, or has an invalid role."""


class StaleSelectionError(ValueError):
    """A graph mutation used an outdated selected-leaf identifier."""


class RetryLimitError(ValueError):
    """A completed persona turn has consumed all retry alternatives."""


class ForkRequiredError(ValueError):
    """The requested branch requires a future continuity fork workflow."""

    def __init__(self, decision: BranchDecision) -> None:
        """Retain the fail-closed decision for the continuity fork workflow.

        Args:
            decision:
                Fork-required decision with exact source references.
        """

        self.decision = decision
        super().__init__(f"Mode action requires a fork: {decision.reason}")
