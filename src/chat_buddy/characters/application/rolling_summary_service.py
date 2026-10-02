"""Durable Ongoing rolling-summary orchestration."""

from datetime import UTC, datetime
from uuid import uuid4

from chat_buddy.characters.domain import (
    CompletedTurn,
    ContextCapacityError,
    ConversationScope,
    ModelRegistry,
    PromptMessage,
    SummaryConflictError,
    SummaryRepository,
    SummaryRevision,
)
from chat_buddy.characters.prompts import (
    PROMPT_OVERHEAD_TOKENS,
    assemble_summary_prompt,
)


class RollingSummaryService:
    """Advance an owned summary through a bounded complete-turn prefix."""

    def __init__(self, repository: SummaryRepository, models: ModelRegistry) -> None:
        """Bind summary persistence and independent provider capabilities.

        Args:
            repository:
                Owned immutable summary persistence.
            models:
                Summary model, gateway, and token-counter registry.
        """

        self._repository = repository
        self._models = models

    def active(self, scope: ConversationScope) -> SummaryRevision | None:
        """Load the active owned summary.

        Args:
            scope:
                Complete required ownership.

        Returns:
            Active durable revision when present.
        """

        return self._repository.get_active(scope)

    def advance(
        self,
        scope: ConversationScope,
        active: SummaryRevision | None,
        omitted: tuple[CompletedTurn, ...],
    ) -> SummaryRevision:
        """Summarize the largest oldest prefix fitting the summary model.

        Args:
            scope:
                Complete required ownership.
            active:
                Previously observed active revision.
            omitted:
                Oldest chronological turns requiring compression.

        Returns:
            Persisted active successor.

        Raises:
            ContextCapacityError:
                If one turn cannot fit or generation/replacement fails.
        """

        if not omitted:
            raise ValueError("At least one omitted turn is required.")

        covered: tuple[CompletedTurn, ...] = ()
        try:
            generation = self._models.resolve_default("summary")
            counter = self._models.token_counter(generation.model.provider)
            prompt: tuple[PromptMessage, ...] = ()
            for turn in omitted:
                candidate = covered + (turn,)
                candidate_prompt = assemble_summary_prompt(
                    active.content if active is not None else None,
                    tuple(
                        (item.user.content, item.persona.content) for item in candidate
                    ),
                )
                if (
                    counter.count(candidate_prompt) + PROMPT_OVERHEAD_TOKENS
                    > generation.input_tokens
                ):
                    break
                covered = candidate
                prompt = candidate_prompt
            if not covered:
                raise ContextCapacityError(
                    "One complete turn exceeds the summary model's input capacity."
                )
            content = (
                self._models.summary_gateway(generation.model.provider)
                .summarize(prompt, generation)
                .strip()
            )
            if not content:
                raise ValueError("Summary provider returned empty content.")

            checkpoint = covered[-1].persona
            replacement = SummaryRevision(
                id=uuid4(),
                scope=scope,
                revision=active.revision + 1 if active is not None else 1,
                predecessor_id=active.id if active is not None else None,
                checkpoint_message_id=checkpoint.id,
                checkpoint_sequence=checkpoint.sequence,
                content=content,
                generation=generation,
                is_active=True,
                created_at=datetime.now(UTC),
            )
            return self._repository.replace(
                replacement,
                expected_revision=active.revision if active is not None else None,
                expected_checkpoint_id=(
                    active.checkpoint_message_id if active is not None else None
                ),
            )
        except ContextCapacityError:
            raise
        except SummaryConflictError:
            current = self._repository.get_active(scope)
            if (
                covered
                and current is not None
                and current.checkpoint_sequence >= covered[-1].persona.sequence
            ):
                return current
            raise ContextCapacityError(
                "The conversation summary changed; retry the response."
            ) from None
        except Exception as error:
            raise ContextCapacityError(
                "Required conversation compression failed; retry the response."
            ) from error
