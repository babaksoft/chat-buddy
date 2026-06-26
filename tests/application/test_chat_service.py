from unittest.mock import Mock
from uuid import uuid4

import pytest

from chat_buddy.application.chat_service import ChatService
from chat_buddy.application.schemas import ChatRequest
from chat_buddy.domain.chat import ChatRole
from chat_buddy.infrastructure.db.models import MessageRole


def test_chat_returns_llm_response() -> None:
    """
    Verify that the service returns the generated
    model response.
    """

    repository = Mock()
    repository.get_messages.return_value = []

    gateway = Mock()
    gateway.generate.return_value = "Hello from Samantha."

    service = ChatService(
        repository=repository,
        llm_gateway=gateway,
    )

    request = ChatRequest(
        conversation_id=uuid4(),
        message="Hello",
    )

    response = service.chat(request)

    assert response.response == "Hello from Samantha."


def test_chat_persists_user_and_assistant_messages() -> None:
    """
    Verify that both user and assistant messages
    are persisted.
    """

    repository = Mock()
    repository.get_messages.return_value = []

    gateway = Mock()
    gateway.generate.return_value = "Hello from Samantha."

    service = ChatService(
        repository=repository,
        llm_gateway=gateway,
    )

    conversation_id = uuid4()

    request = ChatRequest(
        conversation_id=conversation_id,
        message="Hello",
    )

    service.chat(request)

    assert repository.add_message.call_count == 2

    first_call = repository.add_message.call_args_list[0]
    second_call = repository.add_message.call_args_list[1]

    assert first_call.kwargs["role"] == MessageRole.USER

    assert second_call.kwargs["role"] == MessageRole.ASSISTANT


def test_chat_passes_message_to_gateway() -> None:
    repository = Mock()
    repository.get_messages.return_value = [
        Mock(
            role=MessageRole.USER,
            content="Hello",
        )
    ]

    gateway = Mock()
    gateway.generate.return_value = "Hi"

    service = ChatService(
        repository=repository,
        llm_gateway=gateway,
    )

    request = ChatRequest(
        conversation_id=uuid4(),
        message="Hello",
    )

    service.chat(request)

    gateway.generate.assert_called_once()

    messages = gateway.generate.call_args.args[0]
    assert len(messages) == 1
    assert messages[0].role == ChatRole.USER
    assert messages[0].content == "Hello"


def test_chat_uses_conversation_id_for_persistence() -> None:
    repository = Mock()
    repository.get_messages.return_value = []

    gateway = Mock()
    gateway.generate.return_value = "Hi"

    service = ChatService(
        repository=repository,
        llm_gateway=gateway,
    )

    conversation_id = uuid4()

    request = ChatRequest(
        conversation_id=conversation_id,
        message="Hello",
    )

    service.chat(request)

    calls = repository.add_message.call_args_list

    assert calls[0].kwargs["conversation_id"] == conversation_id

    assert calls[1].kwargs["conversation_id"] == conversation_id


def test_chat_persists_assistant_response_content() -> None:
    repository = Mock()
    repository.get_messages.return_value = []

    gateway = Mock()
    gateway.generate.return_value = "Response"

    service = ChatService(
        repository=repository,
        llm_gateway=gateway,
    )

    request = ChatRequest(
        conversation_id=uuid4(),
        message="Hello",
    )

    service.chat(request)

    second_call = repository.add_message.call_args_list[1]

    assert second_call.kwargs["content"] == "Response"


def test_chat_propagates_gateway_errors() -> None:
    repository = Mock()
    repository.get_messages.return_value = []

    gateway = Mock()
    gateway.generate.side_effect = RuntimeError("Ollama unavailable")

    service = ChatService(
        repository=repository,
        llm_gateway=gateway,
    )

    request = ChatRequest(
        conversation_id=uuid4(),
        message="Hello",
    )

    with pytest.raises(RuntimeError):
        service.chat(request)


def test_chat_does_not_persist_assistant_message_when_llm_fails() -> None:
    repository = Mock()
    repository.get_messages.return_value = []

    gateway = Mock()
    gateway.generate.side_effect = RuntimeError()

    service = ChatService(
        repository=repository,
        llm_gateway=gateway,
    )

    request = ChatRequest(
        conversation_id=uuid4(),
        message="Hello",
    )

    with pytest.raises(RuntimeError):
        service.chat(request)

    assert repository.add_message.call_count == 1

    first_call = repository.add_message.call_args_list[0]

    assert first_call.kwargs["role"] == MessageRole.USER


def test_chat_passes_conversation_history_to_gateway() -> None:
    """
    Verify that the complete conversation history
    is passed to the language model gateway.
    """

    repository = Mock()
    repository.get_messages.return_value = [
        Mock(
            role=MessageRole.USER,
            content="Hello",
        ),
        Mock(
            role=MessageRole.ASSISTANT,
            content="Hi there!",
        ),
        Mock(
            role=MessageRole.USER,
            content="How are you?",
        ),
    ]

    gateway = Mock()
    gateway.generate.return_value = "I'm doing well."

    service = ChatService(
        repository=repository,
        llm_gateway=gateway,
    )

    request = ChatRequest(
        conversation_id=uuid4(),
        message="How are you?",
    )

    service.chat(request)

    gateway.generate.assert_called_once()

    messages = gateway.generate.call_args.args[0]

    assert len(messages) == 3

    assert messages[0].role == ChatRole.USER
    assert messages[0].content == "Hello"

    assert messages[1].role == ChatRole.ASSISTANT
    assert messages[1].content == "Hi there!"

    assert messages[2].role == ChatRole.USER
    assert messages[2].content == "How are you?"
