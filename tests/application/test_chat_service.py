from unittest.mock import Mock
from uuid import uuid4

import pytest

from chat_buddy.application.chat_service import ChatService
from chat_buddy.application.schemas import ChatRequest
from chat_buddy.domain import ChatMessage, ChatRole


def _pass_through_memory_service() -> Mock:
    memory_service = Mock()
    memory_service.inject_memories.side_effect = lambda messages: messages

    return memory_service


def test_chat_returns_llm_response() -> None:
    """
    Verify that the service returns the generated
    model response.
    """

    repository = Mock()
    repository.get_messages.return_value = []

    gateway = Mock()
    gateway.generate.return_value = "Hello from Samantha."

    context_builder = Mock()
    memory_service = _pass_through_memory_service()

    service = ChatService(
        repository=repository,
        llm_gateway=gateway,
        context_builder=context_builder,
        memory_service=memory_service,
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

    context_builder = Mock()
    memory_service = _pass_through_memory_service()

    service = ChatService(
        repository=repository,
        llm_gateway=gateway,
        context_builder=context_builder,
        memory_service=memory_service,
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

    assert first_call.kwargs["role"] == ChatRole.USER
    assert second_call.kwargs["role"] == ChatRole.ASSISTANT


def test_chat_uses_conversation_id_for_persistence() -> None:
    repository = Mock()
    repository.get_messages.return_value = []

    gateway = Mock()
    gateway.generate.return_value = "Hi"

    context_builder = Mock()
    memory_service = _pass_through_memory_service()

    service = ChatService(
        repository=repository,
        llm_gateway=gateway,
        context_builder=context_builder,
        memory_service=memory_service,
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

    context_builder = Mock()
    memory_service = _pass_through_memory_service()

    service = ChatService(
        repository=repository,
        llm_gateway=gateway,
        context_builder=context_builder,
        memory_service=memory_service,
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

    context_builder = Mock()
    memory_service = _pass_through_memory_service()

    service = ChatService(
        repository=repository,
        llm_gateway=gateway,
        context_builder=context_builder,
        memory_service=memory_service,
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

    context_builder = Mock()
    memory_service = _pass_through_memory_service()

    service = ChatService(
        repository=repository,
        llm_gateway=gateway,
        context_builder=context_builder,
        memory_service=memory_service,
    )

    request = ChatRequest(
        conversation_id=uuid4(),
        message="Hello",
    )

    with pytest.raises(RuntimeError):
        service.chat(request)

    assert repository.add_message.call_count == 1

    first_call = repository.add_message.call_args_list[0]

    assert first_call.kwargs["role"] == ChatRole.USER


def test_chat_passes_history_to_context_builder() -> None:
    """
    Verify that conversation history is passed to
    the context builder.
    """

    repository = Mock()

    repository.get_messages.return_value = [
        Mock(
            role=ChatRole.USER,
            content="Hello",
        ),
    ]

    context_builder = Mock()
    context_builder.build_context.return_value = []

    gateway = Mock()
    gateway.generate.return_value = "Hi"

    memory_service = _pass_through_memory_service()

    service = ChatService(
        repository=repository,
        llm_gateway=gateway,
        context_builder=context_builder,
        memory_service=memory_service,
    )

    request = ChatRequest(
        conversation_id=uuid4(),
        message="Hello",
    )

    service.chat(request)

    context_builder.build_context.assert_called_once()

    history = context_builder.build_context.call_args.args[0]

    assert len(history) == 1
    assert history[0].role == ChatRole.USER
    assert history[0].content == "Hello"


def test_chat_passes_context_to_gateway() -> None:
    """
    Verify that the context returned by the context
    builder is passed to the language model gateway.
    """

    repository = Mock()
    repository.get_messages.return_value = [
        Mock(
            role=ChatRole.USER,
            content="Hello",
        ),
    ]

    context = [
        ChatMessage(
            role=ChatRole.USER,
            content="Adjusted context",
        ),
    ]

    context_builder = Mock()
    context_builder.build_context.return_value = context

    gateway = Mock()
    gateway.generate.return_value = "Hi"

    memory_service = _pass_through_memory_service()

    service = ChatService(
        repository=repository,
        llm_gateway=gateway,
        context_builder=context_builder,
        memory_service=memory_service,
    )

    request = ChatRequest(
        conversation_id=uuid4(),
        message="Hello",
    )

    service.chat(request)

    context_builder.build_context.assert_called_once()
    gateway.generate.assert_called_once_with(context)


def test_chat_injects_memories_before_context_builder() -> None:
    """
    Verify that memory injection runs before context
    building.
    """

    repository = Mock()
    repository.get_messages.return_value = [
        ChatMessage(
            role=ChatRole.USER,
            content="Hello",
        ),
    ]

    messages_with_memories = [
        ChatMessage(
            role=ChatRole.SYSTEM,
            content="Known facts about the user:\n\n- favorite_language: Python",
        ),
        ChatMessage(
            role=ChatRole.USER,
            content="Hello",
        ),
    ]

    memory_service = Mock()
    memory_service.inject_memories.return_value = messages_with_memories

    context_builder = Mock()
    context_builder.build_context.return_value = messages_with_memories

    gateway = Mock()
    gateway.generate.return_value = "Hi"

    service = ChatService(
        repository=repository,
        llm_gateway=gateway,
        context_builder=context_builder,
        memory_service=memory_service,
    )

    request = ChatRequest(
        conversation_id=uuid4(),
        message="Hello",
    )

    service.chat(request)

    memory_service.inject_memories.assert_called_once()
    context_builder.build_context.assert_called_once_with(
        messages_with_memories,
    )
