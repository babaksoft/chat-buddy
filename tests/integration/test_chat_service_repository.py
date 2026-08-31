from collections.abc import Iterator
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

    def generate_stream(
        self,
        messages: list[ChatMessage],
    ) -> Iterator[str]:
        yield "Hello "
        yield "from "
        yield "Samantha."

    def summarize(
        self,
        messages: list[ChatMessage],
    ) -> str:
        return "Conversation summary."

    def generate_title(
        self,
        messages: list[ChatMessage],
    ) -> str:
        return "Conversation title."

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


class TitleGateway(FakeGateway):
    def __init__(self, title: str) -> None:
        self._title = title

    def generate_title(
        self,
        messages: list[ChatMessage],
    ) -> str:
        return self._title


class BlankTitleGateway(FakeGateway):
    def generate_title(
        self,
        messages: list[ChatMessage],
    ) -> str:
        return "   "


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


def test_chat_auto_titles_first_exchange(
    session: Session,
) -> None:
    """Verify the first exchange persists a generated title."""

    conversation_service = ConversationService(
        repository=ConversationRepository(
            session=session,
        ),
    )
    conversation = conversation_service.create_conversation()

    service = ChatService(
        conversation_service=conversation_service,
        memory_service=_passthrough_memory_service(),
        llm_gateway=TitleGateway("Launch planning"),
        context_builder=_passthrough_context_builder(),
    )

    service.chat(
        ChatRequest(
            conversation_id=conversation.id,
            message="Plan the launch",
        )
    )

    persisted = conversation_service.get_or_create_conversation(conversation.id)

    assert persisted is not None
    assert persisted.title == "Launch planning"


def test_chat_falls_back_to_first_message_title(
    session: Session,
) -> None:
    """Verify blank title output falls back to the first user message."""

    conversation_service = ConversationService(
        repository=ConversationRepository(
            session=session,
        ),
    )
    conversation = conversation_service.create_conversation()

    service = ChatService(
        conversation_service=conversation_service,
        memory_service=_passthrough_memory_service(),
        llm_gateway=BlankTitleGateway(),
        context_builder=_passthrough_context_builder(),
    )

    service.chat(
        ChatRequest(
            conversation_id=conversation.id,
            message="Need a launch plan",
        )
    )

    persisted = conversation_service.get_or_create_conversation(conversation.id)

    assert persisted is not None
    assert persisted.title == "Need a launch plan"


def test_chat_stream_persists_messages(
    session: Session,
) -> None:
    """Verify streaming persists complete message."""

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

    conversation_id, generator = service.stream_chat(
        ChatRequest(
            conversation_id=conversation.id,
            message="Hello",
        )
    )

    chunks = list(generator)

    assert chunks == ["Hello ", "from ", "Samantha."]

    messages = conversation_service.get_messages(conversation_id)
    assert len(messages) == 2
    assert messages[0].role == ChatRole.USER
    assert messages[0].content == "Hello"
    assert messages[1].role == ChatRole.ASSISTANT
    assert messages[1].content == "Hello from Samantha."


def test_chat_stream_auto_titles_first_exchange(
    session: Session,
) -> None:
    """Verify streaming generates title after first exchange."""

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

    _, generator = service.stream_chat(
        ChatRequest(
            conversation_id=conversation.id,
            message="Plan the launch",
        )
    )

    list(generator)

    persisted = conversation_service.get_or_create_conversation(conversation.id)

    assert persisted is not None
    assert persisted.title == "Conversation title."
