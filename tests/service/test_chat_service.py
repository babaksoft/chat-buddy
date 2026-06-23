from unittest.mock import Mock
from uuid import uuid4

import pytest

from chat_buddy.application.chat_service import (
    ChatService,
)
from chat_buddy.application.schemas import (
    ChatRequest,
)
from chat_buddy.infrastructure.db.models import (
    MessageRole,
)


def test_chat_returns_llm_response() -> None:
    """
    Verify that the service returns the generated
    model response.
    """

    repository = Mock()

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

    assert response.response == ("Hello from Samantha.")


def test_chat_persists_user_and_assistant_messages() -> None:
    """
    Verify that both user and assistant messages
    are persisted.
    """

    repository = Mock()

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

    gateway.generate.assert_called_once_with(
        "Hello",
    )


def test_chat_uses_conversation_id_for_persistence() -> None:
    repository = Mock()

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
