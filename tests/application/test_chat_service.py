from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from chat_buddy.chat.application.schemas import ChatRequest, GenerationSelection
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
    ProviderDescriptor,
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
        default_output_token_reserve=512,
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
        submitted_user_content="Hello",
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
    conversation_service.get_open_generation_attempt.return_value = None
    conversation_service.get_latest_retryable_generation_attempt.return_value = None

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


def test_generation_selection_restores_persisted_application_choices() -> None:
    """Verify UI choices are projected through the application service."""

    service, conversations, _, registry, _, _ = _service()
    model = registry.get_model.return_value
    conversation_id = uuid4()
    configuration = GenerationConfiguration(temperature=0.6)
    conversations.get_conversation.return_value = ConversationRecord(
        id=conversation_id,
        title=None,
        provider_id=model.provider_id,
        model_id=model.id,
        requested_generation_configuration=configuration,
    )
    registry.list_providers.return_value = (
        ProviderDescriptor(id=model.provider_id, display_name="Test provider"),
    )
    registry.list_models.return_value = (model,)

    selection = service.get_generation_selection(conversation_id)

    assert isinstance(selection, GenerationSelection)
    assert selection.provider_id == model.provider_id
    assert selection.model_id == model.id
    assert selection.configuration == configuration
    assert selection.providers[0].display_name == "Test provider"
    assert selection.models[0].display_name == "Test model"


def test_generation_selection_change_is_validated_then_persisted() -> None:
    """Verify selector changes become defaults for the next generation only."""

    service, conversations, _, registry, _, _ = _service()
    model = registry.get_model.return_value
    conversation = conversations.get_or_create_conversation.return_value
    configuration = GenerationConfiguration(top_p=0.8)
    conversations.get_conversation.return_value = conversation
    conversations.update_generation_defaults.return_value = ConversationRecord(
        id=conversation.id,
        title=None,
        provider_id=model.provider_id,
        model_id=model.id,
        requested_generation_configuration=configuration,
    )

    updated_id = service.update_generation_selection(
        conversation.id,
        model.provider_id,
        model.id,
        configuration,
    )

    registry.resolve_generation_configuration.assert_called_once_with(
        model, configuration
    )
    conversations.update_generation_defaults.assert_called_once_with(
        conversation.id,
        model.provider_id,
        model.id,
        configuration,
    )
    assert updated_id == conversation.id


def test_recoverable_attempts_expose_only_the_singular_latest_retry_target() -> None:
    """Verify recovery exposes at most one actionable linear-tail attempt."""

    service, conversations, _, registry, _, _ = _service()
    model = registry.get_model.return_value
    conversation_id = uuid4()
    source_id = uuid4()
    retry = _attempt(conversation_id, model)
    retry = GenerationAttemptRecord(
        id=retry.id,
        conversation_id=conversation_id,
        source_user_message_id=source_id,
        submitted_user_content="Edited",
        provider_id=model.provider_id,
        model_id=model.id,
        effective_configuration=GenerationConfiguration(),
        status=GenerationAttemptStatus.PENDING,
        created_at=retry.created_at,
    )
    interrupted = retry.start(at=retry.created_at).interrupt(at=retry.created_at)
    conversations.get_latest_retryable_generation_attempt.return_value = interrupted

    recoverable = service.get_recoverable_generation_attempts(conversation_id)

    assert recoverable == (interrupted,)


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
    conversations.fail_generation_attempt.assert_called_once()
    memory_service.extract_memories.assert_not_called()
    conversations.rename_conversation.assert_not_called()


def test_stream_failure_before_output_marks_attempt_failed() -> None:
    """Verify a provider failure before its first chunk is persisted."""

    service, conversations, gateway, _, _, memory_service = _service()
    gateway.generate_stream.side_effect = RuntimeError("provider unavailable")

    _, stream = service.stream_chat(ChatRequest(conversation_id=None, message="Hello"))
    with pytest.raises(RuntimeError, match="provider unavailable"):
        next(stream)

    failure = conversations.fail_generation_attempt.call_args
    assert failure.kwargs["error_code"] == "provider_error"
    assert failure.kwargs["partial_content"] is None
    conversations.complete_generation_attempt.assert_not_called()
    memory_service.extract_memories.assert_not_called()


def test_stream_failure_flushes_partial_output_to_attempt() -> None:
    """Verify provider failure retains chunks outside completed history.

    Raises:
        RuntimeError:
            Raised by the fake provider after yielding partial output.
    """

    service, conversations, gateway, _, _, memory_service = _service()

    def failing_stream() -> Generator[str, None, None]:
        """Yield one chunk before simulating a provider failure.

        Yields:
            Partial provider-response content.

        Raises:
            RuntimeError:
                Always raised after the first partial chunk.
        """

        yield "Partial"
        raise RuntimeError("stream failed")

    gateway.generate_stream.return_value = failing_stream()
    _, stream = service.stream_chat(ChatRequest(conversation_id=None, message="Hello"))

    assert next(stream) == "Partial"
    with pytest.raises(RuntimeError, match="stream failed"):
        next(stream)

    failure = conversations.fail_generation_attempt.call_args
    assert failure.kwargs["partial_content"] == "Partial"
    conversations.complete_generation_attempt.assert_not_called()
    memory_service.extract_memories.assert_not_called()


def test_stream_consumer_closure_marks_attempt_interrupted() -> None:
    """Verify generator closure flushes partial output as interrupted."""

    service, conversations, _, _, _, memory_service = _service()
    _, stream = service.stream_chat(ChatRequest(conversation_id=None, message="Hello"))

    assert next(stream) == "Hello "
    stream.close()

    interruption = conversations.interrupt_generation_attempt.call_args
    assert interruption.kwargs["partial_content"] == "Hello "
    conversations.complete_generation_attempt.assert_not_called()
    memory_service.extract_memories.assert_not_called()


def test_stream_consumer_closure_before_output_marks_attempt_interrupted() -> None:
    """Verify an unconsumed prepared stream can still be closed durably."""

    service, conversations, gateway, _, _, _ = _service()
    _, stream = service.stream_chat(ChatRequest(conversation_id=None, message="Hello"))

    stream.close()

    conversations.interrupt_generation_attempt.assert_called_once()
    gateway.generate_stream.assert_not_called()


def test_stale_streaming_attempt_is_reconciled_as_interrupted() -> None:
    """Verify resuming a conversation terminates an unowned stream."""

    service, conversations, _, registry, _, _ = _service()
    conversation = conversations.get_or_create_conversation.return_value
    stale = _attempt(conversation.id, registry.get_model.return_value).start(
        at=datetime.now(UTC)
    )
    conversations.get_open_generation_attempt.return_value = stale

    service.reconcile_generation_attempts(conversation.id)

    conversations.interrupt_generation_attempt.assert_called_once()
    conversations.begin_generation_attempt.assert_not_called()
