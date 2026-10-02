"""Typed Characters profile management failures."""


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
