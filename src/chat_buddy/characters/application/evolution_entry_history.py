"""Explicit Entry ownership and mode-specific evolution ancestry policies."""

from chat_buddy.characters.domain import (
    ContinuityEntryRepository,
    ContinuityMode,
    ConversationGraphRepository,
    ConversationScope,
    EntryPosition,
    SelectedPath,
    TimelineDayRepository,
)


class EvolutionEntryHistory:
    """Validate immutable Entry ownership and closure-frozen Day ancestry."""

    def __init__(
        self,
        entries: ContinuityEntryRepository,
        conversations: ConversationGraphRepository,
        days: TimelineDayRepository,
    ) -> None:
        """Bind exact ownership and selected-history readers.

        Args:
            entries:
                Shared relational Entry reader.
            conversations:
                Selected conversation graph reader.
            days:
                Timeline boundary and settled-ancestry reader.
        """

        self._entries = entries
        self._conversations = conversations
        self._days = days

    def selected(
        self, scope: ConversationScope, position: EntryPosition
    ) -> SelectedPath:
        """Read an owned selected path under its mode's history policy.

        Args:
            scope:
                Exact conversation and profile ownership.
            position:
                Expected immutable Entry identity, mode, and order.

        Returns:
            Selected ancestry consistent with persisted Entry and Day facts.

        Raises:
            ValueError:
                If Entry ownership or settled Day ancestry contradicts history.
        """

        entry = self._entries.get(scope, position.entry_id)
        if entry.entry_position != position:
            raise ValueError("Evolution evidence contradicts its owned Entry.")

        path = self._conversations.selected_path(scope)
        if position.mode == ContinuityMode.TIMELINE:
            day = self._days.get(scope, entry.id)
            if day.entry != entry or (
                day.is_closed and path.selected_leaf_id != day.settled_selected_leaf_id
            ):
                raise ValueError("Evolution history contradicts settled Day ancestry.")

        return path
