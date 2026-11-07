"""Inert default for optional Characters diagnostics."""

from chat_buddy.characters.domain import CharactersDiagnostic


class NoOpCharactersDiagnosticObserver:
    """Discard diagnostics when no infrastructure observer is configured."""

    def emit(self, diagnostic: CharactersDiagnostic) -> None:
        """Discard one validated diagnostic.

        Args:
            diagnostic:
                Privacy-safe event to discard.
        """

        del diagnostic
