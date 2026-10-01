"""Typed identity management failures."""


class IdentityNotFoundError(LookupError):
    """The requested identity does not exist."""


class FrozenIdentityError(ValueError):
    """An identity's authored fields can no longer be edited."""


class StaleIdentityError(ValueError):
    """An edit used an outdated identity revision."""
