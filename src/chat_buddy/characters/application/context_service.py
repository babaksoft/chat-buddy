"""Mode-owned eligibility and deterministic response token budgeting."""

from chat_buddy.characters.domain import (
    CompletedTurn,
    ContextCapacityError,
    ContextSelection,
    Continuity,
    ConversationHistory,
    EffectiveGeneration,
    EligibleContext,
    EvolutionProjectionState,
    Identity,
    Message,
    Persona,
    PromptMessage,
    Scene,
    Storyline,
    StorylineMemory,
    SummaryRevision,
    TokenCounter,
)
from chat_buddy.characters.prompts import (
    PROMPT_OVERHEAD_TOKENS,
    assemble_ongoing_prompt,
    assemble_storyline_prompt,
)


class OngoingContextEligibility:
    """Select complete turns after an owned summary checkpoint."""

    def select(
        self,
        history: ConversationHistory,
        summary: SummaryRevision | None,
        current_input: str | None,
    ) -> EligibleContext:
        """Exclude covered turns and isolate the current unmatched input.

        Args:
            history:
                Persisted committed messages and attempt provenance.
            summary:
                Active owned summary when present.
            current_input:
                New uncommitted input during send preflight.

        Returns:
            Eligible summary, complete turns, and current user text.

        Raises:
            ValueError:
                If committed sole-path history is malformed.
        """

        messages = history.messages
        persisted_current: str | None = None
        if messages and messages[-1].role == "user":
            if current_input is not None:
                raise ValueError("Current input duplicates the unmatched user tail.")

            persisted_current = messages[-1].content
            messages = messages[:-1]
        if len(messages) % 2:
            raise ValueError("Committed Ongoing history is not made of whole turns.")

        checkpoint = 0
        if summary is not None:
            if summary.scope != history.scope:
                raise ValueError("Summary ownership does not match the history.")

            checkpoint_message = next(
                (
                    message
                    for message in messages
                    if message.id == summary.checkpoint_message_id
                ),
                None,
            )
            if (
                checkpoint_message is None
                or checkpoint_message.role != "persona"
                or checkpoint_message.sequence != summary.checkpoint_sequence
            ):
                raise ValueError(
                    "Summary checkpoint is not on the selected complete ancestry."
                )
            checkpoint = checkpoint_message.sequence

        uncovered = tuple(
            message for message in messages if message.sequence > checkpoint
        )
        turns = tuple(
            CompletedTurn(user=uncovered[index], persona=uncovered[index + 1])
            for index in range(0, len(uncovered), 2)
        )

        return EligibleContext(
            summary=summary,
            uncovered_turns=turns,
            current_input=(
                current_input if current_input is not None else persisted_current
            ),
        )


class OngoingContextBudgeter:
    """Select a contiguous newest complete-turn suffix within one budget."""

    def assemble(
        self,
        persona: Persona,
        identity: Identity,
        continuity: Continuity,
        context: EligibleContext,
        generation: EffectiveGeneration,
        counter: TokenCounter,
        projections: EvolutionProjectionState | None = None,
    ) -> ContextSelection:
        """Reserve mandatory blocks and greedily add whole turns newest first.

        Args:
            persona:
                Frozen authored persona.
            identity:
                Frozen authored identity.
            continuity:
                Owned starting relationship.
            context:
                Eligible summary, turns, and current input.
            generation:
                Effective response capacity after output reservation.
            counter:
                Provider-specific deterministic estimator.
            projections:
                Current relationship and adaptation caches when initialized.

        Returns:
            Bounded prompt and explicit compression prefix.

        Raises:
            ContextCapacityError:
                If mandatory blocks, summary, latest turn, or current input do not fit.
        """

        turns = context.uncovered_turns
        mandatory_count = min(1, len(turns))
        selected = turns[-mandatory_count:] if mandatory_count else ()
        prompt = self._render(
            persona, identity, continuity, context, selected, projections
        )
        tokens = counter.count(prompt)
        if tokens + PROMPT_OVERHEAD_TOKENS > generation.input_tokens:
            raise ContextCapacityError(
                "Mandatory Ongoing context exceeds this model's capacity."
            )

        omitted = turns[:-mandatory_count] if mandatory_count else ()
        for turn in reversed(omitted):
            candidate_turns = (turn,) + selected
            candidate = self._render(
                persona,
                identity,
                continuity,
                context,
                candidate_turns,
                projections,
            )
            candidate_tokens = counter.count(candidate)
            if candidate_tokens + PROMPT_OVERHEAD_TOKENS > generation.input_tokens:
                break

            selected = candidate_turns
            prompt = candidate
            tokens = candidate_tokens
        omitted_count = len(turns) - len(selected)

        return ContextSelection(
            prompt=prompt,
            included_turns=selected,
            omitted_turns=turns[:omitted_count],
            tokens=tokens,
        )

    @staticmethod
    def _render(
        persona: Persona,
        identity: Identity,
        continuity: Continuity,
        context: EligibleContext,
        turns: tuple[CompletedTurn, ...],
        projections: EvolutionProjectionState | None,
    ) -> tuple[PromptMessage, ...]:
        """Format one candidate using given eligibility.

        Args:
            persona:
                Frozen authored persona.
            identity:
                Frozen authored identity.
            continuity:
                Owned continuity state.
            context:
                Summary and current input.
            turns:
                Selected chronological complete turns.
            projections:
                Current relationship and adaptation caches when initialized.

        Returns:
            Provider-ready prompt messages.
        """

        messages: tuple[Message, ...] = tuple(
            message for turn in turns for message in (turn.user, turn.persona)
        )

        return assemble_ongoing_prompt(
            persona,
            identity,
            continuity,
            messages,
            context.current_input,
            context.summary.content if context.summary is not None else None,
            projections.relationship if projections is not None else None,
            projections.persona_adaptations if projections is not None else None,
        )


class StorylineContextBudgeter:
    """Select one scene's newest complete-turn suffix within its response budget."""

    def assemble(
        self,
        persona: Persona,
        identity: Identity,
        storyline: Storyline,
        scene: Scene,
        context: EligibleContext,
        generation: EffectiveGeneration,
        counter: TokenCounter,
        memories: tuple[StorylineMemory, ...] = (),
        projections: EvolutionProjectionState | None = None,
    ) -> ContextSelection:
        """Reserve Storyline blocks and greedily add whole turns newest first.

        Args:
            persona:
                Frozen authored persona.
            identity:
                Frozen authored identity.
            storyline:
                Owned Storyine continuity.
            scene:
                Exact scene setup and response style.
            context:
                Eligible scene summary, turns, and current input.
            generation:
                Effective response capacity after output reservation.
            counter:
                Provider-specific deterministic estimator.
            memories:
                Dedicated-budget response memories in selector priority order.
            projections:
                Current relationship and adaptation caches when initialized.

        Returns:
            Bounded prompt and explicit compression prefix.

        Raises:
            ContextCapacityError:
                If mandatory Storyline context cannot fit.
        """

        turns = context.uncovered_turns
        mandatory_count = min(1, len(turns))
        selected = turns[-mandatory_count:] if mandatory_count else ()
        selected_memories: tuple[StorylineMemory, ...] = ()
        prompt = self._render(
            persona,
            identity,
            storyline,
            scene,
            context,
            selected,
            selected_memories,
            projections,
        )
        tokens = counter.count(prompt)
        if tokens + PROMPT_OVERHEAD_TOKENS > generation.input_tokens:
            raise ContextCapacityError(
                "Mandatory Storyline context exceeds this model's capacity."
            )

        for memory in memories:
            candidate_memories = (*selected_memories, memory)
            candidate = self._render(
                persona,
                identity,
                storyline,
                scene,
                context,
                selected,
                candidate_memories,
                projections,
            )
            candidate_tokens = counter.count(candidate)
            if candidate_tokens + PROMPT_OVERHEAD_TOKENS <= generation.input_tokens:
                selected_memories = candidate_memories
                prompt = candidate
                tokens = candidate_tokens

        omitted = turns[:-mandatory_count] if mandatory_count else ()
        for turn in reversed(omitted):
            candidate_turns = (turn,) + selected
            candidate = self._render(
                persona,
                identity,
                storyline,
                scene,
                context,
                candidate_turns,
                selected_memories,
                projections,
            )
            candidate_tokens = counter.count(candidate)
            if candidate_tokens + PROMPT_OVERHEAD_TOKENS > generation.input_tokens:
                break

            selected = candidate_turns
            prompt = candidate
            tokens = candidate_tokens
        omitted_count = len(turns) - len(selected)

        return ContextSelection(
            prompt=prompt,
            included_turns=selected,
            omitted_turns=turns[:omitted_count],
            tokens=tokens,
        )

    @staticmethod
    def _render(
        persona: Persona,
        identity: Identity,
        storyline: Storyline,
        scene: Scene,
        context: EligibleContext,
        turns: tuple[CompletedTurn, ...],
        memories: tuple[StorylineMemory, ...],
        projections: EvolutionProjectionState | None,
    ) -> tuple[PromptMessage, ...]:
        """Format one candidate from exact Storyline scene inputs.

        Args:
            persona:
                Frozen authored persona.
            identity:
                Frozen authored identity.
            storyline:
                Owned Storyline snapshot.
            scene:
                Exact scene snapshot.
            context:
                Summary and current input.
            turns:
                Selected chronological complete turns.
            memories:
                Whole response memories admitted before optional older turns.
            projections:
                Current relationship and adaptation caches when initialized.

        Returns:
            Provider-ready prompt messages.
        """

        messages: tuple[Message, ...] = tuple(
            message for turn in turns for message in (turn.user, turn.persona)
        )

        return assemble_storyline_prompt(
            persona,
            identity,
            storyline,
            scene,
            messages,
            context.current_input,
            context.summary.content if context.summary is not None else None,
            memories,
            projections.relationship if projections is not None else None,
            projections.persona_adaptations if projections is not None else None,
        )
