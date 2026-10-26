"""Provider-free Storyline memory and conflict management workflows."""

from uuid import UUID

from chat_buddy.characters.domain import (
    ChangeMemoryStateCommand,
    CorrectMemoryCommand,
    DeleteMemoryCommand,
    DismissMemoryConflictCommand,
    MemoryConflict,
    MemoryExtractionRepository,
    StorylineMemory,
    StorylineMemoryRepository,
)


class StorylineMemoryService:
    """Inspect and manage one Storyline's durable memory boundary."""

    def __init__(
        self,
        memories: StorylineMemoryRepository,
        extraction_records: MemoryExtractionRepository,
    ) -> None:
        """Initialize memory management workflows.

        Args:
            memories:
                Repository for logical lineages and lifecycle transitions.
            extraction_records:
                Repository for persisted extraction conflicts only.
        """

        self._memories = memories
        self._extraction_records = extraction_records

    def list_memories(self, continuity_id: UUID) -> tuple[StorylineMemory, ...]:
        """List every active and excluded memory in a Storyline.

        Args:
            continuity_id:
                Storyline memory boundary.

        Returns:
            Deterministically ordered complete lineages.
        """

        return self._memories.list(continuity_id)

    def inspect_memory(self, continuity_id: UUID, memory_id: UUID) -> StorylineMemory:
        """Inspect one complete continuity-owned lineage.

        Args:
            continuity_id:
                Expected Storyline owner.
            memory_id:
                Logical memory to inspect.

        Returns:
            Complete immutable memory snapshot.
        """

        return self._memories.get(continuity_id, memory_id)

    def correct(self, command: CorrectMemoryCommand) -> StorylineMemory:
        """Apply a guarded user-authored correction.

        Args:
            command:
                Validated active-memory correction.

        Returns:
            Updated complete lineage.
        """

        return self._memories.correct(command)

    def exclude(self, command: ChangeMemoryStateCommand) -> StorylineMemory:
        """Exclude an active memory under its observed revision.

        Args:
            command:
                Guarded exclusion command.

        Returns:
            Updated complete lineage.

        Raises:
            ValueError:
                If the command requests another transition.
        """

        if command.operation != "exclude":
            raise ValueError("The exclusion workflow requires an exclude command")

        return self._memories.change_state(command)

    def reactivate(self, command: ChangeMemoryStateCommand) -> StorylineMemory:
        """Reactivate an excluded memory under its observed revision.

        Args:
            command:
                Guarded reactivation command.

        Returns:
            Updated complete lineage.

        Raises:
            ValueError:
                If the command requests another transition.
        """

        if command.operation != "reactivate":
            raise ValueError("The reactivation workflow requires a reactivate command")

        return self._memories.change_state(command)

    def delete(self, command: DeleteMemoryCommand) -> None:
        """Permanently delete a guarded lineage and its provenance.

        Args:
            command:
                Guarded hard-deletion command.
        """

        self._memories.delete(command)

    def list_conflicts(self, continuity_id: UUID) -> tuple[MemoryConflict, ...]:
        """List unresolved and dismissed conflicts for inspection.

        Args:
            continuity_id:
                Storyline memory boundary.

        Returns:
            Conflicts in deterministic creation order.
        """

        return self._extraction_records.list_conflicts(continuity_id)

    def dismiss_conflict(self, command: DismissMemoryConflictCommand) -> MemoryConflict:
        """Dismiss an unresolved conflict under its memory-revision guard.

        Args:
            command:
                Guarded conflict dismissal.

        Returns:
            Dismissed conflict snapshot.
        """

        return self._extraction_records.dismiss_conflict(command)
