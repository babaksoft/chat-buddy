"""Branch-aware eligibility and contextual Storyline memory selection."""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    CompletedTurn,
    ContextCapacityError,
    ContinuityLifecycle,
    ContinuityMode,
    ConversationGraphRepository,
    ConversationTarget,
    ExtractionBudget,
    IdentityRepository,
    MemoryContextSelector,
    MemoryExtractionContext,
    MemoryRevisionState,
    MemorySelectionResult,
    Message,
    PersonaRepository,
    PromptMessage,
    ScenePosition,
    SceneRepository,
    StorylineMemory,
    StorylineMemoryRepository,
    StorylineRepository,
    StrategyIdentity,
    SummaryRepository,
    TokenCounter,
    UnsupportedContinuityModeError,
)


class StorylineMemoryEligibility:
    """Apply shared Storyline branch and temporal memory eligibility rules."""

    def select(
        self,
        memories: tuple[StorylineMemory, ...],
        continuity_id: UUID,
        target_scene: ScenePosition,
        selected_persona_message_ids: frozenset[UUID],
    ) -> tuple[StorylineMemory, ...]:
        """Return active owned memories supported on the selected past.

        Args:
            memories:
                Candidate logical memories in deterministic repository order.
            continuity_id:
                Expected Storyline owner.
            target_scene:
                Scene whose as-of boundary governs visibility.
            selected_persona_message_ids:
                Persona checkpoints selected across scenes through the target.

        Returns:
            Eligible memories preserving candidate order.
        """

        return tuple(
            memory
            for memory in memories
            if memory.continuity_id == continuity_id
            and memory.current.state == MemoryRevisionState.ACTIVE
            and memory.current.source.persona_message_id in selected_persona_message_ids
            and memory.current.source.occurrence.position <= target_scene.position
            and memory.current.source.learned.position <= target_scene.position
        )


class BaselineMemoryContextSelector:
    """Select whole extraction records with the accepted baseline strategy."""

    _STRATEGY_ID = StrategyIdentity(
        name="baseline.storyline_memory_context", version="1.0.0"
    )

    def __init__(self, counter: TokenCounter) -> None:
        """Bind deterministic provider-specific token accounting.

        Args:
            counter:
                Token estimator used for every complete candidate prompt.
        """

        self._counter = counter

    @property
    def strategy_id(self) -> StrategyIdentity:
        """Return the selector name and behavior version.

        Returns:
            Stable baseline selector identity.
        """

        return self._STRATEGY_ID

    def select(
        self, context: MemoryExtractionContext, budget: ExtractionBudget
    ) -> MemorySelectionResult:
        """Select deterministic whole records without exceeding the budget.

        Args:
            context:
                Complete branch- and time-eligible inputs.
            budget:
                Dedicated extraction input capacity.

        Returns:
            Immutable rendered selection and exact accounting.

        Raises:
            ContextCapacityError:
                If ownership, setup, and exact source evidence do not fit.
        """

        included_turn_ids: set[UUID] = set()
        included_memory_ids: set[UUID] = set()
        summary_included = False

        prompt = self._render(
            context,
            summary_included=False,
            included_turn_ids=included_turn_ids,
            included_memory_ids=included_memory_ids,
        )
        token_count = self._count(prompt, budget)
        if token_count > budget.input_tokens:
            raise ContextCapacityError(
                "Mandatory Storyline extraction context exceeds its capacity."
            )

        if context.summary is not None:
            candidate = self._render(
                context,
                summary_included=True,
                included_turn_ids=included_turn_ids,
                included_memory_ids=included_memory_ids,
            )
            candidate_count = self._count(candidate, budget)
            if candidate_count <= budget.input_tokens:
                summary_included = True
                prompt = candidate
                token_count = candidate_count

        for turn in reversed(context.recent_turns):
            candidate_turn_ids = included_turn_ids | {turn.persona.id}
            candidate = self._render(
                context,
                summary_included=summary_included,
                included_turn_ids=candidate_turn_ids,
                included_memory_ids=included_memory_ids,
            )
            candidate_count = self._count(candidate, budget)
            if candidate_count <= budget.input_tokens:
                included_turn_ids = candidate_turn_ids
                prompt = candidate
                token_count = candidate_count

        ordered_memories = sorted(
            context.eligible_memories,
            key=lambda memory: (
                -memory.current.source.learned.position,
                -memory.current.source.occurrence.position,
                str(memory.id),
            ),
        )
        for memory in ordered_memories:
            candidate_memory_ids = included_memory_ids | {memory.id}
            candidate = self._render(
                context,
                summary_included=summary_included,
                included_turn_ids=included_turn_ids,
                included_memory_ids=candidate_memory_ids,
            )
            candidate_count = self._count(candidate, budget)
            if candidate_count <= budget.input_tokens:
                included_memory_ids = candidate_memory_ids
                prompt = candidate
                token_count = candidate_count

        included_turns = tuple(
            turn.persona.id
            for turn in context.recent_turns
            if turn.persona.id in included_turn_ids
        )
        omitted_turns = tuple(
            turn.persona.id
            for turn in context.recent_turns
            if turn.persona.id not in included_turn_ids
        )

        memory_priority = tuple(memory.id for memory in ordered_memories)
        included_memories = tuple(
            memory_id
            for memory_id in memory_priority
            if memory_id in included_memory_ids
        )
        omitted_memories = tuple(
            memory_id
            for memory_id in memory_priority
            if memory_id not in included_memory_ids
        )

        selection_id = uuid5(
            NAMESPACE_URL,
            "\n".join(
                (
                    self.strategy_id.name,
                    self.strategy_id.version,
                    context.model_dump_json(),
                    str(budget.input_tokens),
                    str(budget.fixed_overhead_tokens),
                    str(summary_included),
                    *prompt,
                )
            ),
        )

        return MemorySelectionResult(
            id=selection_id,
            selector=self.strategy_id,
            context=context,
            included_turn_ids=included_turns,
            omitted_turn_ids=omitted_turns,
            included_memory_ids=included_memories,
            omitted_memory_ids=omitted_memories,
            summary_included=summary_included,
            prompt=prompt,
            token_count=token_count,
            budget=budget,
        )

    def _count(self, prompt: tuple[str, ...], budget: ExtractionBudget) -> int:
        """Count a rendered candidate plus fixed extraction framing.

        Args:
            prompt:
                Ordered extraction context blocks.
            budget:
                Dedicated budget carrying fixed framing overhead.

        Returns:
            Complete estimated input-token count.
        """

        messages = tuple(
            PromptMessage(role="system", content=block) for block in prompt
        )

        return self._counter.count(messages) + budget.fixed_overhead_tokens

    @staticmethod
    def _render(
        context: MemoryExtractionContext,
        *,
        summary_included: bool,
        included_turn_ids: set[UUID],
        included_memory_ids: set[UUID],
    ) -> tuple[str, ...]:
        """Render one candidate in the accepted extraction block order.

        Args:
            context:
                Complete eligible snapshot inputs.
            summary_included:
                Whether to render the compatible summary.
            included_turn_ids:
                Recent persona checkpoints admitted whole.
            included_memory_ids:
                Logical memories admitted whole.

        Returns:
            Ordered immutable text blocks.
        """

        blocks = [
            f"[identity]\n{context.identity_label}",
            f"[persona]\n{context.persona_label}",
            "[starting relationship]\n"
            + context.starting_relationship.model_dump_json(),
            f"[scene setup]\n{context.scene_setup}",
        ]
        if summary_included and context.summary is not None:
            blocks.append(f"[summary]\n{context.summary.content}")

        blocks.extend(
            BaselineMemoryContextSelector._render_turn("recent turn", turn)
            for turn in context.recent_turns
            if turn.persona.id in included_turn_ids
        )

        ordered_memories = sorted(
            (
                memory
                for memory in context.eligible_memories
                if memory.id in included_memory_ids
            ),
            key=lambda memory: (
                -memory.current.source.learned.position,
                -memory.current.source.occurrence.position,
                str(memory.id),
            ),
        )
        blocks.extend(
            "\n".join(
                (
                    f"[memory:{memory.id}]",
                    f"Subject: {memory.current.subject}",
                    f"Content: {memory.current.content}",
                )
            )
            for memory in ordered_memories
        )

        blocks.append(
            BaselineMemoryContextSelector._render_turn(
                "new evidence", context.source_turn
            )
        )

        return tuple(blocks)

    @staticmethod
    def _render_turn(label: str, turn: CompletedTurn) -> str:
        """Render one complete turn as an indivisible labeled record.

        Args:
            label:
                Context role for the turn.
            turn:
                Complete user and persona exchange.

        Returns:
            Rendered whole-record block.
        """

        return "\n".join(
            (
                f"[{label}:{turn.persona.id}]",
                f"User: {turn.user.content}",
                f"Persona: {turn.persona.content}",
            )
        )


class StorylineExtractionContextService:
    """Build one read-only extraction snapshot from persisted Storyline state."""

    def __init__(
        self,
        identities: IdentityRepository,
        personas: PersonaRepository,
        storylines: StorylineRepository,
        scenes: SceneRepository,
        conversations: ConversationGraphRepository,
        summaries: SummaryRepository,
        memories: StorylineMemoryRepository,
        eligibility: StorylineMemoryEligibility,
        selector: MemoryContextSelector,
    ) -> None:
        """Bind owned readers and pure selection policies.

        Args:
            identities:
                Identity snapshot reader.
            personas:
                Persona snapshot reader.
            storylines:
                Storyline ownership reader.
            scenes:
                Ordered scene reader.
            conversations:
                Selected graph-path reader.
            summaries:
                Branch-compatible summary reader.
            memories:
                Continuity-owned memory reader.
            eligibility:
                Shared branch and temporal memory policy.
            selector:
                Versioned dedicated-budget selector.
        """

        self._identities = identities
        self._personas = personas
        self._storylines = storylines
        self._scenes = scenes
        self._conversations = conversations
        self._summaries = summaries
        self._memories = memories
        self._eligibility = eligibility
        self._selector = selector

    def build(
        self,
        target: ConversationTarget,
        source_persona_message_id: UUID,
        budget: ExtractionBudget,
    ) -> MemorySelectionResult:
        """Build a bounded snapshot for one still-selected complete turn.

        Args:
            target:
                Exact Storyline scene ownership.
            source_persona_message_id:
                Selected completed response that is mandatory new evidence.
            budget:
                Dedicated extraction input budget.

        Returns:
            Reproducible provider-independent extraction selection.

        Raises:
            UnsupportedContinuityModeError:
                If the target is not a Storyline scene.
            ArchivedContinuityError:
                If the Storyline is no longer active.
            ValueError:
                If the source is not a complete selected turn or state is
                internally inconsistent.
        """

        if target.mode != ContinuityMode.STORYLINE or target.scene_id is None:
            raise UnsupportedContinuityModeError(
                "Memory extraction snapshots require a Storyline scene"
            )

        storyline = self._storylines.get(
            target.scope.identity_id,
            target.scope.persona_id,
            target.scope.continuity_id,
        )
        if storyline.lifecycle != ContinuityLifecycle.ACTIVE:
            raise ArchivedContinuityError(
                "Archived Storylines cannot request extraction snapshots"
            )

        scene = self._scenes.get(target.scope, target.scene_id)
        sequence = self._scenes.list(storyline)
        selected_paths = {
            candidate.id: self._conversations.selected_path(candidate.scope)
            for candidate in sequence.scenes
            if candidate.position <= scene.position
        }
        source_path = selected_paths[scene.id]
        source_index = next(
            (
                index
                for index, node in enumerate(source_path.messages)
                if node.id == source_persona_message_id
            ),
            None,
        )
        if (
            source_index is None
            or source_index == 0
            or source_path.messages[source_index].role != "persona"
            or source_path.messages[source_index - 1].role != "user"
        ):
            raise ValueError("Extraction source must be a complete selected turn")

        source_messages = tuple(
            Message(
                id=node.id,
                scope=node.scope,
                sequence=index + 1,
                role=node.role,
                content=node.content,
                created_at=node.created_at,
            )
            for index, node in enumerate(source_path.messages[: source_index + 1])
        )
        source_turn = CompletedTurn(
            user=source_messages[-2], persona=source_messages[-1]
        )
        summary = self._summaries.get_current(
            target.scope, path_leaf_id=source_persona_message_id
        )
        checkpoint = 0
        if summary is not None:
            checkpoint_message = next(
                (
                    message
                    for message in source_messages[:-2]
                    if message.id == summary.checkpoint_message_id
                    and message.sequence == summary.checkpoint_sequence
                    and message.role == "persona"
                ),
                None,
            )
            if checkpoint_message is None:
                summary = None
            else:
                checkpoint = checkpoint_message.sequence

        recent_messages = tuple(
            message for message in source_messages[:-2] if message.sequence > checkpoint
        )
        if len(recent_messages) % 2:
            raise ValueError("Selected extraction ancestry is not made of whole turns")

        recent_turns = tuple(
            CompletedTurn(
                user=recent_messages[index], persona=recent_messages[index + 1]
            )
            for index in range(0, len(recent_messages), 2)
        )
        selected_persona_ids = frozenset(
            node.id
            for path in selected_paths.values()
            for node in path.messages
            if node.role == "persona"
        )
        scene_position = ScenePosition(scene_id=scene.id, position=scene.position)
        eligible_memories = self._eligibility.select(
            self._memories.list(storyline.id),
            storyline.id,
            scene_position,
            selected_persona_ids,
        )
        identity = self._identities.get(storyline.identity_id)
        persona = self._personas.get(storyline.persona_id)
        context = MemoryExtractionContext(
            scope=target.scope,
            scene=scene_position,
            identity_label=identity.details.name,
            persona_label=persona.core.name,
            starting_relationship=storyline.relationship,
            scene_setup=scene.details.setup,
            summary=summary,
            recent_turns=recent_turns,
            eligible_memories=eligible_memories,
            source_turn=source_turn,
        )

        return self._selector.select(context, budget)
