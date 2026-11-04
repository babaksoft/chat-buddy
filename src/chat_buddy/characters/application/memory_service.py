"""Provider-free Storyline memory and conflict management workflows."""

from uuid import UUID

from chat_buddy.characters.domain import (
    ChangeMemoryStateCommand,
    ContinuityMemory,
    ContinuityMemoryRepository,
    CorrectMemoryCommand,
    DeleteMemoryCommand,
    DismissMemoryConflictCommand,
    MemoryConflict,
    MemoryExtractionRepository,
)


class ContinuityMemoryService:
    """Inspect and manage one continuity's durable memory boundary."""

    def __init__(
        self,
        memories: ContinuityMemoryRepository,
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

    def list_memories(self, continuity_id: UUID) -> tuple[ContinuityMemory, ...]:
        """List every active and excluded memory in a Storyline.

        Args:
            continuity_id:
                Continuity memory boundary.

        Returns:
            Deterministically ordered complete lineages.
        """

        return self._memories.list(continuity_id)

    def inspect_memory(self, continuity_id: UUID, memory_id: UUID) -> ContinuityMemory:
        """Inspect one complete continuity-owned lineage.

        Args:
            continuity_id:
                Expected continuity owner.
            memory_id:
                Logical memory to inspect.

        Returns:
            Complete immutable memory snapshot.
        """

        return self._memories.get(continuity_id, memory_id)

    def correct(self, command: CorrectMemoryCommand) -> ContinuityMemory:
        """Apply a guarded user-authored correction.

        Args:
            command:
                Validated active-memory correction.

        Returns:
            Updated complete lineage.
        """

        return self._memories.correct(command)

    def exclude(self, command: ChangeMemoryStateCommand) -> ContinuityMemory:
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

    def reactivate(self, command: ChangeMemoryStateCommand) -> ContinuityMemory:
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
                Continuity memory boundary.

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


# Transitional import names are removed by Slice 7.
StorylineMemoryService = ContinuityMemoryService
TimelineMemoryService = ContinuityMemoryService
