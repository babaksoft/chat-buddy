class ContextWindowExceededError(Exception):
    """
    Raised when the conversation exceeds the
    available model context window.
    """


class InvalidGenerationConfigurationError(ValueError):
    """Raised when generation settings cannot form a valid request."""


class UnknownProviderError(LookupError):
    """Raised when a provider identifier is not registered for Chat."""


class UnknownModelError(LookupError):
    """Raised when a model identifier is not registered for a provider."""


class ProviderInvocationError(RuntimeError):
    """Raised when a configured provider cannot complete an invocation."""


class InvalidGenerationAttemptTransitionError(ValueError):
    """Raised when a generation attempt lifecycle transition is invalid."""
