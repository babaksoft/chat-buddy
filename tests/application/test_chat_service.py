from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from chat_buddy.chat.application.schemas import ChatRequest
from chat_buddy.chat.application.service import ChatService
from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    ConversationRecord,
    GenerationAttemptRecord,
    GenerationAttemptStatus,
    GenerationConfiguration,
    InvalidGenerationConfigurationError,
    ModelDescriptor,
    ModelId,
    ProviderId,
)


def _model(*, supports_streaming: bool = True) -> ModelDescriptor:
    """Create the selected model used by application tests.

    Args:
        supports_streaming:
            Whether the model supports streaming responses.

    Returns:
        Immutable test model descriptor.
    """

    return ModelDescriptor(
        provider_id=ProviderId("test-provider"),
        id=ModelId("test-model"),
        display_name="Test model",
        context_window_tokens=4_096,
        supports_streaming=supports_streaming,
        supported_generation_parameters=frozenset(),
        default_generation_configuration=GenerationConfiguration(),
        token_counter=Mock(),
    )


def _attempt(conversation_id: UUID, model: ModelDescriptor) -> GenerationAttemptRecord:
    """Create a pending attempt returned by the persistence test double.

    Args:
        conversation_id:
            Conversation identifier for the attempt.
        model:
            Selected model descriptor.

    Returns:
        Pending generation attempt.
    """

    return GenerationAttemptRecord(
        id=uuid4(),
        conversation_id=conversation_id,
        source_user_message_id=uuid4(),
        provider_id=model.provider_id,
        model_id=model.id,
        effective_configuration=GenerationConfiguration(),
        status=GenerationAttemptStatus.PENDING,
        created_at=datetime.now(UTC),
    )


def _service(
    *,
    model: ModelDescriptor | None = None,
    title: str | None = "Generated title",
) -> tuple[ChatService, Mock, Mock, Mock, Mock, Mock]:
    """Build a Chat service and its application-level test doubles.

    Args:
        model:
            Optional selected model.
        title:
            Title-generator result.

    Returns:
        Service, conversation, gateway, registry, context, and memory doubles.
    """

    selected_model = model or _model()
    conversation_id = uuid4()
    conversation_service = Mock()
    conversation_service.get_or_create_conversation.return_value = ConversationRecord(
        id=conversation_id,
        title=None,
        provider_id=selected_model.provider_id,
        model_id=selected_model.id,
    )
    conversation_service.start_generation_attempt.return_value = _attempt(
        conversation_id,
        selected_model,
    )
    conversation_service.get_messages.return_value = [
        ChatMessage(ChatRole.USER, "Hello")
    ]

    gateway = Mock()
    gateway.generate.return_value = "Hello from the model."
    gateway.generate_stream.return_value = iter(["Hello ", "from the model."])
    resolver = Mock()
    resolver.resolve.return_value = gateway

    effective = GenerationConfiguration(temperature=0.4)
    registry = Mock()
    registry.get_model.return_value = selected_model
    registry.get_default_model.return_value = selected_model
    registry.resolve_generation_configuration.return_value = effective

    context_builder = Mock()
    context_builder.build_context.side_effect = lambda messages, selected: messages
    memory_service = Mock()
    memory_service.inject_memories.side_effect = lambda messages: messages
    title_generator = Mock()
    title_generator.generate_title.return_value = title

    service = ChatService(
        conversation_service=conversation_service,
        memory_service=memory_service,
        context_builder=context_builder,
        provider_registry=registry,
        response_gateway_resolver=resolver,
        title_generator=title_generator,
    )
    return (
        service,
        conversation_service,
        gateway,
        registry,
        context_builder,
        memory_service,
    )


def test_chat_routes_effective_configuration_through_attempt_lifecycle() -> None:
    """Verify synchronous generation uses one validated lifecycle."""

    service, conversations, gateway, registry, context_builder, _ = _service()

    response = service.chat(ChatRequest(conversation_id=None, message="Hello"))

    model = registry.get_model.return_value
    effective = registry.resolve_generation_configuration.return_value
    conversations.start_generation_attempt.assert_called_once_with(
        response.conversation_id,
        "Hello",
        model.provider_id,
        model.id,
        effective,
    )
    conversations.begin_generation_attempt.assert_called_once()
    context_builder.build_context.assert_called_once_with(
        conversations.get_messages.return_value,
        model,
    )
    gateway.generate.assert_called_once_with(
        conversations.get_messages.return_value,
        model.id,
        effective,
    )
    conversations.complete_generation_attempt.assert_called_once()
    assert response.response == "Hello from the model."


def test_stream_chat_uses_the_same_attempt_lifecycle() -> None:
    """Verify streaming begins and completes the prepared attempt."""

    service, conversations, gateway, registry, _, _ = _service()

    _, stream = service.stream_chat(ChatRequest(conversation_id=None, message="Hello"))
    chunks = list(stream)

    assert chunks == ["Hello ", "from the model."]
    gateway.generate_stream.assert_called_once_with(
        conversations.get_messages.return_value,
        registry.get_model.return_value.id,
        registry.resolve_generation_configuration.return_value,
    )
    conversations.begin_generation_attempt.assert_called_once()
    completion = conversations.complete_generation_attempt.call_args
    assert completion.args[1] == "Hello from the model."


def test_new_conversation_persists_registry_default_before_attempt() -> None:
    """Verify a new conversation adopts the registered default selection."""

    service, conversations, _, registry, _, _ = _service()
    model = registry.get_model.return_value
    initial = conversations.get_or_create_conversation.return_value
    initial = ConversationRecord(id=initial.id, title=None)
    selected = ConversationRecord(
        id=initial.id,
        title=None,
        provider_id=model.provider_id,
        model_id=model.id,
    )
    conversations.get_or_create_conversation.return_value = initial
    conversations.update_generation_defaults.return_value = selected

    service.chat(ChatRequest(conversation_id=None, message="Hello"))

    registry.get_default_model.assert_called_once_with()
    conversations.update_generation_defaults.assert_called_once_with(
        initial.id,
        model.provider_id,
        model.id,
        GenerationConfiguration(),
    )


def test_streaming_capability_is_validated_before_attempt_is_started() -> None:
    """Verify a non-streaming model is rejected before persisting a user turn."""

    service, conversations, _, _, _, _ = _service(
        model=_model(supports_streaming=False)
    )

    with pytest.raises(InvalidGenerationConfigurationError):
        service.stream_chat(ChatRequest(conversation_id=None, message="Hello"))

    conversations.start_generation_attempt.assert_not_called()


def test_completed_turn_effects_run_after_atomic_completion() -> None:
    """Verify title and memory effects cannot precede assistant-message commit."""

    service, conversations, _, _, _, memory_service = _service()
    calls = Mock()
    calls.attach_mock(conversations.complete_generation_attempt, "complete")
    calls.attach_mock(memory_service.extract_memories, "memory")

    service.chat(ChatRequest(conversation_id=None, message="Hello"))

    assert [call[0] for call in calls.mock_calls] == ["complete", "memory"]
    conversations.rename_conversation.assert_called_once()


def test_provider_error_does_not_complete_or_run_turn_effects() -> None:
    """Verify unsuccessful synchronous generation remains outside completion."""

    service, conversations, gateway, _, _, memory_service = _service()
    gateway.generate.side_effect = RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.chat(ChatRequest(conversation_id=None, message="Hello"))

    conversations.complete_generation_attempt.assert_not_called()
    memory_service.extract_memories.assert_not_called()
    conversations.rename_conversation.assert_not_called()
