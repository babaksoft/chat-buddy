"""Structured logging adapter for privacy-safe Characters diagnostics."""

import logging
from functools import lru_cache

from chat_buddy.characters.domain import CharactersDiagnostic

logger = logging.getLogger(__name__)


class LoggingCharactersDiagnosticObserver:
    """Write validated allowlisted diagnostics as structured log attributes."""

    def emit(self, diagnostic: CharactersDiagnostic) -> None:
        """Log one diagnostic without authored or generated content.

        Args:
            diagnostic:
                Validated allowlisted diagnostic.
        """

        attributes = {
            f"characters_{name}": value
            for name, value in diagnostic.model_dump(
                mode="json", exclude_none=True
            ).items()
        }
        logger.info(
            "Characters operation reached an observable state.", extra=attributes
        )


@lru_cache(maxsize=1)
def default_characters_diagnostic_observer() -> LoggingCharactersDiagnosticObserver:
    """Return the process-wide structured diagnostic logger.

    Returns:
        Shared stateless logging observer.
    """

    return LoggingCharactersDiagnosticObserver()
