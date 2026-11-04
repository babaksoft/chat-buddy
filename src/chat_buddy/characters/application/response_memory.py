"""Continuity response-memory eligibility loading and bounded selection."""

from chat_buddy.characters.domain import (
    ContinuityEntryRepository,
    ContinuityMemory,
    ContinuityMemoryRepository,
    ContinuityMode,
    ConversationGraphRepository,
    ConversationTarget,
    ResponseMemoryBudget,
    ResponseMemorySelection,
    ResponseMemorySelector,
    StrategyIdentity,
    TokenCounter,
)
from chat_buddy.characters.prompts import assemble_continuity_memory_blocks


class BaselineResponseMemorySelector:
    """Select complete response memories in stable subject order."""

    _STRATEGY_ID = StrategyIdentity(
        name="baseline.continuity_response_memory", version="1.0.0"
    )

    @property
    def strategy_id(self) -> StrategyIdentity:
        """Return the response selector name and behavior version.

        Returns:
            Stable baseline selector identity.
        """

        return self._STRATEGY_ID

    def select(
        self,
        memories: tuple[ContinuityMemory, ...],
        budget: ResponseMemoryBudget,
        counter: TokenCounter,
    ) -> ResponseMemorySelection:
        """Admit deterministic whole records within dedicated capacity.

        Args:
            memories:
                Branch- and time-eligible Storyline records.
            budget:
                Dedicated response-memory capacity.
            counter:
                Provider-specific exact token counter.

        Returns:
            Versioned selection with exact inclusion and omission accounting.
        """

        ordered = tuple(
            sorted(
                memories,
                key=lambda memory: (
                    memory.current.subject.casefold(),
                    str(memory.id),
                ),
            )
        )
        included: tuple[ContinuityMemory, ...] = ()
        tokens = 0
        for memory in ordered:
            candidate = (*included, memory)
            candidate_tokens = counter.count(
                assemble_continuity_memory_blocks(candidate)
            )
            if candidate_tokens <= budget.input_tokens:
                included = candidate
                tokens = candidate_tokens
        included_ids = {memory.id for memory in included}

        return ResponseMemorySelection(
            selector=self.strategy_id,
            eligible_memory_ids=tuple(memory.id for memory in ordered),
            included_memories=included,
            omitted_memory_ids=tuple(
                memory.id for memory in ordered if memory.id not in included_ids
            ),
            token_count=tokens,
            budget=budget,
        )


class BaselineTimelineResponseMemorySelector(BaselineResponseMemorySelector):
    """Transitional name for the shared Continuity response selector."""


class ContinuityResponseMemoryService:
    """Load and budget eligible memory through shared Entry ownership."""

    def __init__(
        self,
        entries: ContinuityEntryRepository,
        conversations: ConversationGraphRepository,
        memories: ContinuityMemoryRepository,
        selector: ResponseMemorySelector,
        budget: ResponseMemoryBudget,
    ) -> None:
        """Bind shared Entry, branch, memory, and budgeting capabilities.

        Args:
            entries:
                Immutable Entry ownership and position reader.
            conversations:
                Selected graph-path reader.
            memories:
                Continuity-scoped eligible-memory reader.
            selector:
                Independently versioned response-memory selector.
            budget:
                Dedicated memory capacity for every response.
        """

        self._entries = entries
        self._conversations = conversations
        self._memories = memories
        self._selector = selector
        self._budget = budget

    def select(
        self, target: ConversationTarget, counter: TokenCounter
    ) -> ResponseMemorySelection:
        """Select eligible memory as of an exact Entry and selected past.

        Args:
            target:
                Exact Storyline Scene or Timeline Day target.
            counter:
                Active response provider's token counter.

        Returns:
            Bounded versioned response-memory selection.

        Raises:
            ValueError:
                If the target is Ongoing and therefore has no Entry.
        """

        if target.mode == ContinuityMode.ONGOING or target.entry_id is None:
            raise ValueError("Response memory requires an Entry-owned target")
        entry = self._entries.get(target.scope, target.entry_id)
        entries = self._entries.list(
            target.scope.identity_id,
            target.scope.persona_id,
            target.scope.continuity_id,
            target.mode,
        )
        selected_persona_ids = frozenset(
            node.id
            for candidate in entries
            if candidate.position <= entry.position
            for node in self._conversations.selected_path(candidate.scope).messages
            if node.role == "persona"
        )
        eligible = self._memories.list_eligible(
            target.scope.continuity_id,
            entry.position,
            selected_persona_ids,
        )
        eligible = tuple(
            memory
            for memory in eligible
            if memory.current.source.learned.mode == target.mode
            and memory.current.source.occurrence.mode == target.mode
        )
        return self._selector.select(eligible, self._budget, counter)


# Transitional import names are removed by Slice 7.
StorylineResponseMemoryService = ContinuityResponseMemoryService
TimelineResponseMemoryService = ContinuityResponseMemoryService
