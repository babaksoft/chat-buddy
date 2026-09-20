"""Conversation-scoped durable rolling-summary orchestration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from math import floor
from uuid import UUID, uuid4

from chat_buddy.chat.application.config import RollingSummaryConfig
from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    CompletedTurn,
    ContextInputs,
    GenerationConfiguration,
    ModelDescriptor,
    RollingSummaryGenerator,
    SummaryLifecycle,
    SummaryProvenance,
    SummaryRecord,
    SummaryRepository,
)

logger = logging.getLogger(__name__)

_MEMORY_CONTEXT_HEADER = "Relevant memory"
_SUMMARY_CONTEXT_HEADER = "Conversation summary"


class RollingSummaryService:
    """Create durable summary versions while retaining recent complete turns."""

    def __init__(
        self,
        repository: SummaryRepository,
        generator: RollingSummaryGenerator,
        config: RollingSummaryConfig,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize rolling-summary orchestration.

        Args:
            repository:
                Conversation-scoped summary persistence.
            generator:
                Utility generator for replacement summary text.
            config:
                Trigger and recent-turn retention policy.
            clock:
                Optional timezone-aware clock used by tests.
        """

        self._repository = repository
        self._generator = generator
        self._config = config
        self._clock = clock or (lambda: datetime.now(UTC))

    def update_summary(
        self,
        inputs: ContextInputs,
        model: ModelDescriptor,
        configuration: GenerationConfiguration,
    ) -> SummaryRecord | None:
        """Persist a required rolling update and return the active summary.

        Summary generation is best effort. Provider, validation, and persistence
        failures leave the last durable version active so context budgeting can
        apply its normal fallback policy. Invalid repository coverage is rejected
        because it would make a checkpoint unsafe.

        Args:
            inputs:
                Eligible memories and current input for the response boundary.
                Summary and turn values are reloaded authoritatively.
            model:
                Selected response model and token counter.
            configuration:
                Effective generation settings used for output reservation.

        Returns:
            The active summary after an update, or ``None`` if none is required.

        Raises:
            ValueError:
                If prompt capacity, repository coverage, or the clock is invalid.
        """

        active = self._repository.get_active_summary(inputs.conversation_id)
        turns = self._repository.get_uncovered_completed_turns(inputs.conversation_id)
        self._validate_coverage(inputs.conversation_id, active, turns)

        prompt_capacity = (
            model.context_window_tokens
            - self._config.prompt_overhead_tokens
            - model.output_token_reserve(configuration)
        )
        if prompt_capacity <= 0:
            raise ValueError("Summary policy requires a positive prompt capacity.")
        trigger = floor(prompt_capacity * self._config.summary_trigger_ratio)

        formatted = self._format_context(inputs, active, turns)
        if model.token_counter.count_tokens(formatted) <= trigger:
            return active

        coverable_count = max(
            0,
            len(turns) - self._config.minimum_recent_turns,
        )
        covered = self._select_turns_to_cover(
            inputs,
            active,
            turns,
            coverable_count,
            trigger,
            model,
        )
        if covered:
            return self._generate_and_persist(inputs, active, covered)

        if active is not None and self._summary_cost(active.content, model) > trigger:
            return self._compact_active_summary(inputs, active, model)

        return active

    def _select_turns_to_cover(
        self,
        inputs: ContextInputs,
        active: SummaryRecord | None,
        turns: tuple[CompletedTurn, ...],
        coverable_count: int,
        trigger: int,
        model: ModelDescriptor,
    ) -> tuple[CompletedTurn, ...]:
        """Select the smallest oldest prefix needed to reach the trigger.

        Args:
            inputs:
                Eligible boundary inputs.
            active:
                Current durable summary, when present.
            turns:
                Authoritative uncovered completed turns.
            coverable_count:
                Number of oldest turns allowed to enter the summary.
            trigger:
                Formatted token threshold for summarization.
            model:
                Selected model and token counter.

        Returns:
            Oldest chronological prefix to incorporate.
        """

        for count in range(1, coverable_count + 1):
            remaining = turns[count:]
            formatted = self._format_context(inputs, active, remaining)
            if model.token_counter.count_tokens(formatted) <= trigger:
                return turns[:count]
        return turns[:coverable_count]

    def _generate_and_persist(
        self,
        inputs: ContextInputs,
        active: SummaryRecord | None,
        covered: tuple[CompletedTurn, ...],
    ) -> SummaryRecord | None:
        """Generate and atomically persist one advancing summary version.

        Args:
            inputs:
                Eligible boundary inputs identifying the conversation.
            active:
                Current active summary, when present.
            covered:
                Newly covered chronological turn prefix.

        Returns:
            Persisted replacement, or the prior active version after failure.
        """

        try:
            content = self._generator.generate_summary(
                active.content if active is not None else None,
                covered,
            ).strip()
            replacement = self._new_summary(
                inputs.conversation_id,
                content,
                covered[-1].assistant_message_id,
                active,
            )
            return self._repository.replace_active_summary(
                replacement,
                expected_active_id=active.id if active is not None else None,
            )
        except Exception:
            logger.warning(
                "Rolling summary update failed for conversation %s; preserving "
                "the prior active version.",
                inputs.conversation_id,
                exc_info=True,
            )

            return active

    def _compact_active_summary(
        self,
        inputs: ContextInputs,
        active: SummaryRecord,
        model: ModelDescriptor,
    ) -> SummaryRecord:
        """Compact an oversized active summary without advancing its checkpoint.

        Args:
            inputs:
                Eligible boundary inputs identifying the conversation.
            active:
                Oversized active summary.
            model:
                Selected model and token counter.

        Returns:
            Smaller persisted successor or the unchanged active summary.
        """

        try:
            content = self._generator.generate_summary(active.content, ()).strip()
            if self._summary_cost(content, model) >= self._summary_cost(
                active.content, model
            ):
                return active

            replacement = self._new_summary(
                inputs.conversation_id,
                content,
                active.checkpoint_message_id,
                active,
            )
            return self._repository.replace_active_summary(
                replacement,
                expected_active_id=active.id,
            )
        except Exception:
            logger.warning(
                "Summary compaction failed for conversation %s; preserving the "
                "prior active version.",
                inputs.conversation_id,
                exc_info=True,
            )

            return active

    def _new_summary(
        self,
        conversation_id: UUID,
        content: str,
        checkpoint_message_id: UUID,
        active: SummaryRecord | None,
    ) -> SummaryRecord:
        """Build a validated active summary version.

        Args:
            conversation_id:
                Owning conversation identifier.
            content:
                Generated and normalized summary text.
            checkpoint_message_id:
                New authoritative assistant-message checkpoint.
            active:
                Predecessor version, when replacing one.

        Returns:
            Validated immutable summary version.

        Raises:
            ValueError:
                If the clock or generated values are invalid.
        """

        created_at = self._clock()
        if created_at.tzinfo is None:
            raise ValueError("Rolling-summary clock must be timezone-aware.")

        return SummaryRecord(
            id=uuid4(),
            conversation_id=conversation_id,
            content=content,
            created_at=created_at,
            lifecycle=SummaryLifecycle.ACTIVE,
            provenance=SummaryProvenance(
                conversation_id=conversation_id,
                checkpoint_message_id=checkpoint_message_id,
                predecessor_id=active.id if active is not None else None,
            ),
        )

    @staticmethod
    def _validate_coverage(
        conversation_id: UUID,
        active: SummaryRecord | None,
        turns: tuple[CompletedTurn, ...],
    ) -> None:
        """Reject cross-conversation, duplicate, or non-advancing coverage.

        Args:
            conversation_id:
                Selected conversation identifier.
            active:
                Current active summary, when present.
            turns:
                Repository-supplied uncovered turns.

        Raises:
            ValueError:
                If repository results cannot safely advance a checkpoint.
        """

        if active is not None and active.conversation_id != conversation_id:
            raise ValueError("The active summary belongs to another conversation.")
        if any(turn.conversation_id != conversation_id for turn in turns):
            raise ValueError("Uncovered turns belong to another conversation.")
        if len({turn.attempt_id for turn in turns}) != len(turns):
            raise ValueError("Uncovered completed turns must be unique.")
        if active is not None and any(
            turn.assistant_message_id == active.checkpoint_message_id for turn in turns
        ):
            raise ValueError("Uncovered turns cannot repeat the active checkpoint.")

    @staticmethod
    def _format_context(
        inputs: ContextInputs,
        active: SummaryRecord | None,
        turns: tuple[CompletedTurn, ...],
    ) -> list[ChatMessage]:
        """Format all currently eligible content for trigger measurement.

        Args:
            inputs:
                Eligible memories and current input.
            active:
                Authoritative active summary.
            turns:
                Authoritative uncovered completed turns.

        Returns:
            Provider-neutral formatted message list.
        """

        messages = [
            ChatMessage(
                ChatRole.SYSTEM,
                f"{_MEMORY_CONTEXT_HEADER}: {memory.subject}\n\n{memory.content}",
            )
            for memory in inputs.memories
        ]
        if active is not None:
            messages.append(
                ChatMessage(
                    ChatRole.SYSTEM,
                    f"{_SUMMARY_CONTEXT_HEADER}:\n\n{active.content}",
                )
            )
        for turn in turns:
            messages.extend(turn.messages)
        messages.append(inputs.current_input)
        return messages

    @staticmethod
    def _summary_cost(content: str, model: ModelDescriptor) -> int:
        """Count one formatted summary message.

        Args:
            content:
                Summary text to measure.
            model:
                Selected model and token counter.

        Returns:
            Formatted token cost.
        """

        return model.token_counter.count_tokens(
            [
                ChatMessage(
                    ChatRole.SYSTEM,
                    f"{_SUMMARY_CONTEXT_HEADER}:\n\n{content}",
                )
            ]
        )
