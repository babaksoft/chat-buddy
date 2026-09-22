"""Repository-backed integration coverage for Stage 3 context assembly."""

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from chat_buddy.chat.application.config import ContextBudgetConfig, RollingSummaryConfig
from chat_buddy.chat.application.context_builder import (
    ContextAssemblyService,
    DefaultContextBudgeter,
    DefaultContextEligibility,
)
from chat_buddy.chat.application.service import RollingSummaryService
from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    CompletedTurn,
    ExtractionReceiptRecord,
    GenerationConfiguration,
    MemoryCandidate,
    MemoryExtractionOutcome,
    ModelDescriptor,
    ModelId,
    ProviderId,
)
from chat_buddy.chat.infrastructure.db.repositories import (
    ConversationRepository,
    MemoryRepository,
    SummaryRepository,
)


class MessageCounter:
    """Assign every formatted message a stable ten-token cost."""

    def count_tokens(self, messages: list[ChatMessage]) -> int:
        """Count formatted messages.

        Args:
            messages:
                Provider-facing context.

        Returns:
            Ten tokens per message.
        """

        return len(messages) * 10


class StableSummaryGenerator:
    """Return compact deterministic rolling summaries."""

    def generate_summary(
        self,
        prior_summary: str | None,
        turns: tuple[CompletedTurn, ...],
    ) -> str:
        """Return one compact summary value.

        Args:
            prior_summary:
                Prior summary content, when replacing a version.
            turns:
                Newly covered turns.

        Returns:
            Stable non-empty summary text.
        """

        return "compact summary"


def _model(provider_id: ProviderId, model_id: ModelId) -> ModelDescriptor:
    """Create the constrained model used to force rolling checkpoints.

    Returns:
        Test model descriptor.
    """

    return ModelDescriptor(
        provider_id=provider_id,
        id=model_id,
        display_name="Small model",
        context_window_tokens=80,
        supports_streaming=True,
        supported_generation_parameters=frozenset(),
        default_generation_configuration=GenerationConfiguration(),
        token_counter=MessageCounter(),
        default_output_token_reserve=20,
    )


def _complete_turn(
    repository: ConversationRepository,
    conversation_id: UUID,
    number: int,
    provider_id: ProviderId,
    model_id: ModelId,
) -> CompletedTurn:
    """Persist and return one completed linear turn.

    Args:
        repository:
            Conversation repository.
        conversation_id:
            Owning conversation identifier.
        number:
            Stable content suffix and time offset.
        provider_id:
            Response provider recorded for the attempt.
        model_id:
            Provider-local model recorded for the attempt.

    Returns:
        Exact completed turn.
    """

    pending = repository.start_generation_attempt(
        conversation_id,
        f"question {number}",
        provider_id,
        model_id,
        GenerationConfiguration(),
    )
    repository.begin_generation_attempt(pending.id, at=pending.created_at)
    completed = repository.complete_generation_attempt(
        pending.id,
        f"answer {number}",
        at=pending.created_at + timedelta(seconds=1),
    )
    assert completed.assistant_message_id is not None
    assert completed.finished_at is not None
    return CompletedTurn(
        conversation_id=conversation_id,
        attempt_id=completed.id,
        user_message_id=completed.source_user_message_id,
        assistant_message_id=completed.assistant_message_id,
        user_content=completed.submitted_user_content,
        assistant_content=f"answer {number}",
        completed_at=completed.finished_at,
    )


def _assembler(
    memories: MemoryRepository,
    summaries: SummaryRepository,
) -> ContextAssemblyService:
    """Compose real repositories with deterministic context services.

    Args:
        memories:
            Chat-wide memory repository.
        summaries:
            Conversation summary repository.

    Returns:
        Fully composed context assembly service.
    """

    return ContextAssemblyService(
        eligibility=DefaultContextEligibility(memories, summaries),
        budgeter=DefaultContextBudgeter(
            ContextBudgetConfig(
                prompt_overhead_tokens=0,
                minimum_recent_turns=2,
            )
        ),
        rolling_summarizer=RollingSummaryService(
            repository=summaries,
            generator=StableSummaryGenerator(),
            config=RollingSummaryConfig(
                prompt_overhead_tokens=0,
                summary_trigger_ratio=0.5,
                minimum_recent_turns=2,
            ),
        ),
    )


@pytest.mark.parametrize(
    ("provider_id", "model_id"),
    [
        pytest.param(ProviderId("ollama"), ModelId("local-small"), id="local"),
        pytest.param(ProviderId("openai"), ModelId("cloud-small"), id="cloud"),
    ],
)
def test_long_context_rolls_multiple_checkpoints_and_reuses_global_memory(
    session: Session, provider_id: ProviderId, model_id: ModelId
) -> None:
    """Long provider-backed history stays bounded across Chat conversations.

    Args:
        session:
            Isolated database session.
        provider_id:
            Local or cloud response-provider identifier.
        model_id:
            Selected provider-local model identifier.
    """

    conversations = ConversationRepository(session)
    memories = MemoryRepository(session)
    summaries = SummaryRepository(session)
    assembler = _assembler(memories, summaries)
    model = _model(provider_id, model_id)
    configuration = GenerationConfiguration()
    conversation_a = conversations.create_conversation()
    first = _complete_turn(conversations, conversation_a.id, 1, provider_id, model_id)
    memories.process_extraction(
        first,
        (MemoryCandidate("city", "The user lives in Tehran."),),
        ExtractionReceiptRecord(
            generation_attempt_id=first.attempt_id,
            outcome=MemoryExtractionOutcome.SUCCEEDED,
            attempt_count=1,
            completed_at=first.completed_at + timedelta(seconds=1),
        ),
    )
    second = _complete_turn(conversations, conversation_a.id, 2, provider_id, model_id)
    third = _complete_turn(conversations, conversation_a.id, 3, provider_id, model_id)

    first_result = assembler.assemble(
        conversation_a.id,
        ChatMessage(ChatRole.USER, "question 4"),
        model,
        configuration,
    )
    first_summary = summaries.get_active_summary(conversation_a.id)
    assert first_summary is not None
    assert first_summary.checkpoint_message_id == first.assistant_message_id
    assert first_result.prompt_tokens <= first_result.prompt_capacity
    assert first_result.included_attempt_ids == (
        second.attempt_id,
        third.attempt_id,
    )

    fourth = _complete_turn(conversations, conversation_a.id, 4, provider_id, model_id)
    second_result = assembler.assemble(
        conversation_a.id,
        ChatMessage(ChatRole.USER, "question 5"),
        model,
        configuration,
    )
    second_summary = summaries.get_active_summary(conversation_a.id)
    assert second_summary is not None
    assert second_summary.id != first_summary.id
    assert second_summary.checkpoint_message_id == second.assistant_message_id
    assert second_result.prompt_tokens <= second_result.prompt_capacity
    assert second_result.included_attempt_ids == (
        third.attempt_id,
        fourth.attempt_id,
    )

    conversation_b = conversations.create_conversation()
    cross_conversation = assembler.assemble(
        conversation_b.id,
        ChatMessage(ChatRole.USER, "Where do I live?"),
        model,
        configuration,
    )

    assert cross_conversation.included_memory_ids == (
        memories.list_eligible_memories()[0].id,
    )
    assert cross_conversation.included_attempt_ids == ()
    assert any("Tehran" in message.content for message in cross_conversation.messages)
    assert all(
        "compact summary" not in message.content
        for message in cross_conversation.messages
    )
