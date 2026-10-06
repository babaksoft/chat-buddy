"""Typed validation, operational and management failures."""


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


class ConfirmationConflictError(ValueError):
    """A confirmation identifier was reused for different submitted data."""


class UnsupportedContinuityModeError(ValueError):
    """The requested continuity mode cannot yet be started."""


class ArchivedContinuityError(ValueError):
    """An archived continuity cannot accept writes."""


class ModelResolutionError(ValueError):
    """The provider/model selection is not configured."""


class UnsupportedGenerationError(ValueError):
    """A capability, parameter, or output reserve is unsupported."""


class ProviderInvocationError(RuntimeError):
    """A provider failed; the message contains no provider payload or secrets."""


class InvalidProviderResponseError(ProviderInvocationError):
    """A provider returned malformed or empty summary output."""


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


class InvalidParentError(ValueError):
    """A message parent is absent, foreign, cyclic, or has an invalid role."""


class StaleSelectionError(ValueError):
    """A graph mutation used an outdated selected-leaf identifier."""


class RetryLimitError(ValueError):
    """A completed persona turn has consumed all retry alternatives."""


class ForkRequiredError(ValueError):
    """The requested mode action requires a future continuity fork workflow."""
