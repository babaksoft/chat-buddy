"""Repository-backed integration tests for durable rolling summaries."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chat_buddy.chat.application.config import RollingSummaryConfig
from chat_buddy.chat.application.service import RollingSummaryService
from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    CompletedTurn,
    ContextInputs,
    GenerationConfiguration,
    GenerationParameter,
    ModelDescriptor,
    ModelId,
    ProviderId,
)
from chat_buddy.chat.infrastructure.db.models import Summary
from chat_buddy.chat.infrastructure.db.repositories import (
    ConversationRepository,
    SummaryRepository,
)


class MessageCounter:
    """Count a fixed cost per formatted message for integration tests."""

    def count_tokens(self, messages: list[ChatMessage]) -> int:
        """Return ten tokens per message.

        Args:
            messages:
                Formatted messages.

        Returns:
            Deterministic token count.
        """

        return len(messages) * 10


class RecordingGenerator:
    """Generate deterministic text while recording conversation turns."""

    def __init__(self) -> None:
        """Initialize an empty call record."""

        self.calls: list[tuple[str | None, tuple[CompletedTurn, ...]]] = []

    def generate_summary(
        self,
        prior_summary: str | None,
        turns: tuple[CompletedTurn, ...],
    ) -> str:
        """Create summary text from recorded turn identifiers.

        Args:
            prior_summary:
                Prior summary text.
            turns:
                Newly covered turns.

        Returns:
            Non-empty deterministic summary text.
        """

        self.calls.append((prior_summary, turns))
        return "summary " + " ".join(str(turn.attempt_id) for turn in turns)


def _model() -> ModelDescriptor:
    """Create the selected model used by integration tests.

    Returns:
        Deterministic model descriptor.
    """

    return ModelDescriptor(
        provider_id=ProviderId("test"),
        id=ModelId("model"),
        display_name="Test model",
        context_window_tokens=80,
        supports_streaming=True,
        supported_generation_parameters=frozenset(
            {GenerationParameter.MAX_OUTPUT_TOKENS}
        ),
        default_generation_configuration=GenerationConfiguration(),
        token_counter=MessageCounter(),
        default_output_token_reserve=20,
    )


def _complete_turn(
    repository: ConversationRepository,
    conversation_id: UUID,
    number: int,
) -> CompletedTurn:
    """Persist one complete linear turn.

    Args:
        repository:
            Conversation persistence adapter.
        conversation_id:
            Owning conversation identifier.
        number:
            Stable content and time offset.

    Returns:
        Exact completed turn.
    """

    pending = repository.start_generation_attempt(
        conversation_id,
        f"question {number}",
        ProviderId("test"),
        ModelId("model"),
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


def _service(
    summaries: SummaryRepository,
    generator: RecordingGenerator,
) -> RollingSummaryService:
    """Build a repository-backed rolling-summary service.

    Args:
        summaries:
            Summary persistence adapter.
        generator:
            Recording utility fake.

    Returns:
        Configured service.
    """

    return RollingSummaryService(
        repository=summaries,
        generator=generator,
        config=RollingSummaryConfig(
            prompt_overhead_tokens=0,
            summary_trigger_ratio=0.5,
            minimum_recent_turns=2,
        ),
    )


def _inputs(conversation_id: UUID) -> ContextInputs:
    """Create current input for one conversation.

    Args:
        conversation_id:
            Selected conversation identifier.

    Returns:
        Context boundary input.
    """

    return ContextInputs(
        conversation_id,
        ChatMessage(ChatRole.USER, "next question"),
    )


def test_persisted_summary_resumes_and_rolls_without_crossing_conversations(
    session: Session,
) -> None:
    """Persisted checkpoints isolate two conversations and skip covered turns.

    Args:
        session:
            Isolated database session.
    """

    conversations = ConversationRepository(session)
    summaries = SummaryRepository(session)
    first_conversation = conversations.create_conversation()
    second_conversation = conversations.create_conversation()
    first_turns = tuple(
        _complete_turn(conversations, first_conversation.id, number)
        for number in range(3)
    )
    second_turns = tuple(
        _complete_turn(conversations, second_conversation.id, number)
        for number in range(10, 13)
    )
    generator = RecordingGenerator()
    service = _service(summaries, generator)

    first_summary = service.update_summary(
        _inputs(first_conversation.id), _model(), GenerationConfiguration()
    )
    second_summary = service.update_summary(
        _inputs(second_conversation.id), _model(), GenerationConfiguration()
    )
    resumed = _service(summaries, generator).update_summary(
        _inputs(first_conversation.id), _model(), GenerationConfiguration()
    )

    assert first_summary is not None
    assert second_summary is not None
    assert resumed == first_summary
    assert first_summary.checkpoint_message_id == first_turns[0].assistant_message_id
    assert second_summary.checkpoint_message_id == second_turns[0].assistant_message_id
    assert len(generator.calls) == 2
    assert all(
        turn.conversation_id == first_conversation.id for turn in generator.calls[0][1]
    )
    assert all(
        turn.conversation_id == second_conversation.id for turn in generator.calls[1][1]
    )

    fourth = _complete_turn(conversations, first_conversation.id, 4)
    replacement = service.update_summary(
        _inputs(first_conversation.id), _model(), GenerationConfiguration()
    )

    assert replacement is not None
    assert replacement.predecessor_id == first_summary.id
    assert replacement.checkpoint_message_id == first_turns[1].assistant_message_id
    assert fourth.attempt_id not in {turn.attempt_id for turn in generator.calls[-1][1]}
    assert summaries.get_active_summary(second_conversation.id) == second_summary


def test_deleting_conversation_hard_deletes_its_summary_versions(
    session: Session,
) -> None:
    """Conversation ownership cascades deletion across summary lineage.

    Args:
        session:
            Isolated database session.
    """

    conversations = ConversationRepository(session)
    summaries = SummaryRepository(session)
    conversation = conversations.create_conversation()
    for number in range(3):
        _complete_turn(conversations, conversation.id, number)
    generator = RecordingGenerator()
    active = _service(summaries, generator).update_summary(
        _inputs(conversation.id), _model(), GenerationConfiguration()
    )
    assert active is not None

    conversations.delete_conversation(conversation.id)

    version_count = session.scalar(
        select(func.count())
        .select_from(Summary)
        .where(Summary.conversation_id == conversation.id)
    )
    assert version_count == 0
