from unittest.mock import Mock
from uuid import uuid4

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
