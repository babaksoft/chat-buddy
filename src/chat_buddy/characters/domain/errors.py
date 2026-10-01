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
