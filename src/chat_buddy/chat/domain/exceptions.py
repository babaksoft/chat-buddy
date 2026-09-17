class ContextWindowExceededError(Exception):
    """
    Raised when the conversation exceeds the
    available model context window.
    """


class InvalidGenerationConfigurationError(ValueError):
    """Raised when generation settings cannot form a valid request."""


class InvalidGenerationAttemptTransitionError(ValueError):
    """Raised when a generation attempt lifecycle transition is invalid."""
