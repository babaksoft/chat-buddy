from unittest.mock import Mock

from sqlalchemy.orm import Session

from chat_buddy.application.schemas import ChatRequest
from chat_buddy.application.service import (
    ChatService,
    ConversationService,
    MemoryService,
)
from chat_buddy.domain import (
    ChatMessage,
    ChatRole,
    ExtractedMemory,
    LLMGateway,
)
from chat_buddy.infrastructure.db.repositories import (
    ConversationRepository,
    MemoryRepository,
)
from chat_buddy.prompts.memory import MEMORY_CONTEXT_HEADER


class FakeGateway(LLMGateway):
    def generate(
        self,
        messages: list[ChatMessage],
    ) -> str:
        return "Hello from Samantha."

    def summarize(
        self,
        messages: list[ChatMessage],
    ) -> str:
        return "Conversation summary."

    def extract_memories(
        self,
        messages: list[ChatMessage],
    ) -> list[ExtractedMemory]:
        return []


class RecordingGateway(FakeGateway):
    def __init__(self) -> None:
        self.last_messages: list[ChatMessage] = []

    def generate(
        self,
        messages: list[ChatMessage],
    ) -> str:
        self.last_messages = messages

        return super().generate(messages)


def _passthrough_context_builder() -> Mock:
    context_builder = Mock()
    context_builder.build_context.side_effect = lambda messages: messages

    return context_builder


def _passthrough_memory_service() -> Mock:
    memory_service = Mock()
    memory_service.inject_memories.side_effect = lambda messages: messages

    return memory_service


def test_chat_persists_messages(
    session: Session,
) -> None:
    """Verify message and response are both persisted."""

    conversation_service = ConversationService(
        repository=ConversationRepository(
            session=session,
        ),
    )
    conversation = conversation_service.create_conversation()

    service = ChatService(
        conversation_service=conversation_service,
        memory_service=_passthrough_memory_service(),
        llm_gateway=FakeGateway(),
        context_builder=_passthrough_context_builder(),
    )

    service.chat(
        ChatRequest(
            conversation_id=conversation.id,
            message="Hello",
        )
    )

    messages = conversation_service.get_messages(conversation.id)

    assert len(messages) == 2

    assert messages[0].role == ChatRole.USER
    assert messages[0].content == "Hello"

    assert messages[1].role == ChatRole.ASSISTANT
    assert messages[1].content == "Hello from Samantha."


def test_chat_returns_response(
    session: Session,
) -> None:
    """Verify LLM response is returned by chat service."""

    conversation_service = ConversationService(
        repository=ConversationRepository(
            session=session,
        ),
    )
    conversation = conversation_service.create_conversation()

    service = ChatService(
        conversation_service=conversation_service,
        memory_service=_passthrough_memory_service(),
        llm_gateway=FakeGateway(),
        context_builder=_passthrough_context_builder(),
    )

    response = service.chat(
        ChatRequest(
            conversation_id=conversation.id,
            message="Hello",
        )
    )

    assert response.response == "Hello from Samantha."


def test_chat_supports_multiple_turns(
    session: Session,
) -> None:
    """Verify chat service persists multiple-turn conversations."""

    conversation_service = ConversationService(
        repository=ConversationRepository(
            session=session,
        ),
    )
    conversation = conversation_service.create_conversation()

    service = ChatService(
        conversation_service=conversation_service,
        memory_service=_passthrough_memory_service(),
        llm_gateway=FakeGateway(),
        context_builder=_passthrough_context_builder(),
    )

    service.chat(
        ChatRequest(
            conversation_id=conversation.id,
            message="Hi",
        )
    )

    service.chat(
        ChatRequest(
            conversation_id=conversation.id,
            message="How are you?",
        )
    )

    messages = conversation_service.get_messages(conversation.id)

    assert len(messages) == 4


def test_chat_injects_persisted_memories_into_llm_context(
    session: Session,
) -> None:
    """Verify persisted memories reach the language model."""

    memory_repository = MemoryRepository(session)
    memory_service = MemoryService(memory_repository)
    memory_repository.save_memory(
        key="favorite_language",
        value="Python",
    )

    conversation_service = ConversationService(
        repository=ConversationRepository(
            session=session,
        ),
    )
    conversation = conversation_service.create_conversation()
    gateway = RecordingGateway()

    context_builder = Mock()
    context_builder.build_context.side_effect = lambda messages: messages

    service = ChatService(
        conversation_service=conversation_service,
        memory_service=memory_service,
        llm_gateway=gateway,
        context_builder=context_builder,
    )

    service.chat(
        ChatRequest(
            conversation_id=conversation.id,
            message="Hello",
        )
    )

    assert len(gateway.last_messages) == 2

    assert gateway.last_messages[0].role == ChatRole.SYSTEM
    assert MEMORY_CONTEXT_HEADER in gateway.last_messages[0].content
    assert "- favorite_language: Python" in gateway.last_messages[0].content

    assert gateway.last_messages[1].role == ChatRole.USER
    assert gateway.last_messages[1].content == "Hello"
