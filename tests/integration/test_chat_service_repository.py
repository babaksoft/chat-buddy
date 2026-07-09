from unittest.mock import Mock

from sqlalchemy.orm import Session

from chat_buddy.application.chat_service import (
    ChatRequest,
    ChatService,
)
from chat_buddy.domain.chat import ChatMessage, ChatRole
from chat_buddy.domain.extracted_memory import ExtractedMemory
from chat_buddy.domain.llm_gateway import LLMGateway
from chat_buddy.infrastructure.db.repositories import ConversationRepository


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


def test_chat_persists_messages(
    session: Session,
) -> None:
    repository = ConversationRepository(
        session,
    )

    conversation = repository.create_conversation()

    service = ChatService(
        repository=repository,
        llm_gateway=FakeGateway(),
        context_builder=Mock(),
        memory_service=Mock(),
    )

    service.chat(
        ChatRequest(
            conversation_id=conversation.id,
            message="Hello",
        )
    )

    messages = repository.get_messages(
        conversation.id,
    )

    assert len(messages) == 2

    assert messages[0].role == ChatRole.USER
    assert messages[0].content == "Hello"

    assert messages[1].role == ChatRole.ASSISTANT

    assert messages[1].content == "Hello from Samantha."


def test_chat_returns_response(
    session: Session,
) -> None:
    repository = ConversationRepository(
        session,
    )

    conversation = repository.create_conversation()

    service = ChatService(
        repository=repository,
        llm_gateway=FakeGateway(),
        context_builder=Mock(),
        memory_service=Mock(),
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
    repository = ConversationRepository(
        session,
    )

    conversation = repository.create_conversation()

    service = ChatService(
        repository=repository,
        llm_gateway=FakeGateway(),
        context_builder=Mock(),
        memory_service=Mock(),
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

    messages = repository.get_messages(
        conversation.id,
    )

    assert len(messages) == 4
