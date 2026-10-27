"""Storyline response-memory eligibility loading and bounded selection."""

from chat_buddy.characters.domain import (
    ConversationGraphRepository,
    ResponseMemoryBudget,
    ResponseMemorySelection,
    ResponseMemorySelector,
    Scene,
    SceneRepository,
    Storyline,
    StorylineMemory,
    StorylineMemoryRepository,
    StrategyIdentity,
    TokenCounter,
)
from chat_buddy.characters.prompts import assemble_storyline_memory_blocks


class BaselineResponseMemorySelector:
    """Select complete response memories in stable subject order."""

    _STRATEGY_ID = StrategyIdentity(
        name="baseline.storyline_response_memory", version="1.0.0"
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
        memories: tuple[StorylineMemory, ...],
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
        included: tuple[StorylineMemory, ...] = ()
        tokens = 0
        for memory in ordered:
            candidate = (*included, memory)
            candidate_tokens = counter.count(
                assemble_storyline_memory_blocks(candidate)
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


class StorylineResponseMemoryService:
    """Load eligible response memory from selected Storyline histories."""

    def __init__(
        self,
        scenes: SceneRepository,
        conversations: ConversationGraphRepository,
        memories: StorylineMemoryRepository,
        selector: ResponseMemorySelector,
        budget: ResponseMemoryBudget,
    ) -> None:
        """Bind owned readers and the independent response selector.

        Args:
            scenes:
                Ordered Storyline scene reader.
            conversations:
                Selected graph-path reader.
            memories:
                Continuity-scoped eligible-memory reader.
            selector:
                Independently versioned response-memory selector.
            budget:
                Dedicated memory capacity for every response.
        """

        self._scenes = scenes
        self._conversations = conversations
        self._memories = memories
        self._selector = selector
        self._budget = budget

    def select(
        self, storyline: Storyline, scene: Scene, counter: TokenCounter
    ) -> ResponseMemorySelection:
        """Select eligible memory as of one exact scene and selected past.

        Args:
            storyline:
                Owning Storyline snapshot.
            scene:
                Target chronological scene.
            counter:
                Active response provider's token counter.

        Returns:
            Bounded versioned response-memory selection.
        """

        sequence = self._scenes.list(storyline)
        selected_persona_ids = frozenset(
            node.id
            for candidate in sequence.scenes
            if candidate.position <= scene.position
            for node in self._conversations.selected_path(candidate.scope).messages
            if node.role == "persona"
        )
        eligible = self._memories.list_eligible(
            storyline.id,
            scene.position,
            selected_persona_ids,
        )

        return self._selector.select(eligible, self._budget, counter)
