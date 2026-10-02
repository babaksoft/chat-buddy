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
    ContextAssemblyResult,
    ContextWindowExceededError,
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
) -> tuple[ChatService, Mock, Mock, Mock, Mock, Mock, Mock]:
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
    generation_attempt_service = Mock()
    pending_attempt = _attempt(
        conversation_id,
        selected_model,
    )
    generation_attempt_service.start_generation_attempt.return_value = pending_attempt
    generation_attempt_service.complete_generation_attempt.return_value = (
        pending_attempt.start(at=pending_attempt.created_at).complete(
            assistant_message_id=uuid4(),
            at=pending_attempt.created_at,
        )
    )
    conversation_service.get_messages.return_value = []
    generation_attempt_service.get_open_generation_attempt.return_value = None
    generation_attempt_service.get_latest_retryable_generation_attempt.return_value = (
        None
    )

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

    context_assembler = Mock()
    assembled_messages = (ChatMessage(ChatRole.USER, "Hello"),)
    context_assembler.assemble.return_value = ContextAssemblyResult(
        messages=assembled_messages,
        prompt_tokens=1,
        prompt_capacity=100,
    )
    memory_extraction_service = Mock()
    title_generator = Mock()
    title_generator.generate_title.return_value = title

    service = ChatService(
        conversation_service=conversation_service,
        generation_attempt_service=generation_attempt_service,
        memory_extraction_service=memory_extraction_service,
        context_assembler=context_assembler,
        provider_registry=registry,
        response_gateway_resolver=resolver,
        title_generator=title_generator,
    )
    return (
        service,
        conversation_service,
        generation_attempt_service,
        gateway,
        registry,
        context_assembler,
        memory_extraction_service,
    )


def test_chat_routes_effective_configuration_through_attempt_lifecycle() -> None:
    """Verify synchronous generation uses one validated lifecycle."""

    service, _, attempts, gateway, registry, context_assembler, _ = _service()

    response = service.chat(ChatRequest(conversation_id=None, message="Hello"))

    model = registry.get_model.return_value
    effective = registry.resolve_generation_configuration.return_value
    attempts.start_generation_attempt.assert_called_once_with(
        response.conversation_id,
        "Hello",
        model.provider_id,
        model.id,
        effective,
    )
    attempts.begin_generation_attempt.assert_called_once()
    context_assembler.assemble.assert_called_once_with(
        response.conversation_id,
        ChatMessage(ChatRole.USER, "Hello"),
        model,
        effective,
    )
    gateway.generate.assert_called_once_with(
        list(context_assembler.assemble.return_value.messages),
        model.id,
        effective,
    )
    attempts.complete_generation_attempt.assert_called_once()
    assert response.response == "Hello from the model."


def test_stream_chat_uses_the_same_attempt_lifecycle() -> None:
    """Verify streaming begins and completes the prepared attempt."""

    service, _, attempts, gateway, registry, context_assembler, _ = _service()

    _, stream = service.stream_chat(ChatRequest(conversation_id=None, message="Hello"))
    chunks = list(stream)

    assert chunks == ["Hello ", "from the model."]
    gateway.generate_stream.assert_called_once_with(
        list(context_assembler.assemble.return_value.messages),
        registry.get_model.return_value.id,
        registry.resolve_generation_configuration.return_value,
    )
    attempts.begin_generation_attempt.assert_called_once()
    completion = attempts.complete_generation_attempt.call_args
    assert completion.args[1] == "Hello from the model."


def test_new_conversation_persists_registry_default_before_attempt() -> None:
    """Verify a new conversation adopts the registered default selection."""

    service, conversations, _, _, registry, _, _ = _service()
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

    service, conversations, _, _, registry, _, _ = _service()
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

    service, conversations, _, _, registry, _, _ = _service()
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

    service, _, attempts, _, registry, _, _ = _service()
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
    attempts.get_latest_retryable_generation_attempt.return_value = interrupted

    recoverable = service.get_recoverable_generation_attempts(conversation_id)

    assert recoverable == (interrupted,)


def test_streaming_capability_is_validated_before_attempt_is_started() -> None:
    """Verify a non-streaming model is rejected before persisting a user turn."""

    service, _, attempts, _, _, _, _ = _service(model=_model(supports_streaming=False))

    with pytest.raises(InvalidGenerationConfigurationError):
        service.stream_chat(ChatRequest(conversation_id=None, message="Hello"))

    attempts.start_generation_attempt.assert_not_called()


def test_context_failure_creates_no_attempt_and_invokes_no_provider() -> None:
    """Verify mandatory budget failure occurs before durable turn creation."""

    service, _, attempts, gateway, _, context_assembler, _ = _service()
    context_assembler.assemble.side_effect = ContextWindowExceededError(
        "mandatory context is too large"
    )

    with pytest.raises(ContextWindowExceededError):
        service.chat(ChatRequest(conversation_id=None, message="Hello"))

    attempts.start_generation_attempt.assert_not_called()
    gateway.generate.assert_not_called()
    gateway.generate_stream.assert_not_called()


def test_post_response_effects_run_after_atomic_completion() -> None:
    """Verify title and memory effects cannot precede assistant-message commit."""

    service, conversations, attempts, _, _, _, memory_extraction_service = _service()
    calls = Mock()
    calls.attach_mock(attempts.complete_generation_attempt, "complete")
    calls.attach_mock(memory_extraction_service.process, "memory")

    service.chat(ChatRequest(conversation_id=None, message="Hello"))

    assert [call[0] for call in calls.mock_calls] == ["complete", "memory"]
    completed = attempts.complete_generation_attempt.return_value
    turn = memory_extraction_service.process.call_args.args[0]
    assert turn.conversation_id == completed.conversation_id
    assert turn.attempt_id == completed.id
    assert turn.user_message_id == completed.source_user_message_id
    assert turn.assistant_message_id == completed.assistant_message_id
    assert turn.user_content == completed.submitted_user_content
    assert turn.assistant_content == "Hello from the model."
    conversations.rename_conversation.assert_called_once()


def test_extraction_failure_does_not_change_completed_response() -> None:
    """Verify post-completion extraction remains best-effort for callers."""

    service, conversations, attempts, _, _, _, memory_extraction_service = _service()
    memory_extraction_service.process.side_effect = RuntimeError(
        "terminal receipt unavailable"
    )

    response = service.chat(ChatRequest(conversation_id=None, message="Hello"))

    assert response.response == "Hello from the model."
    attempts.complete_generation_attempt.assert_called_once()
    conversations.rename_conversation.assert_called_once()


def test_provider_error_does_not_complete_or_run_turn_effects() -> None:
    """Verify unsuccessful synchronous generation remains outside completion."""

    service, conversations, attempts, gateway, _, _, memory_extraction_service = (
        _service()
    )
    gateway.generate.side_effect = RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.chat(ChatRequest(conversation_id=None, message="Hello"))

    attempts.complete_generation_attempt.assert_not_called()
    attempts.fail_generation_attempt.assert_called_once()
    memory_extraction_service.process.assert_not_called()
    conversations.rename_conversation.assert_not_called()


def test_stream_failure_before_output_marks_attempt_failed() -> None:
    """Verify a provider failure before its first chunk is persisted."""

    service, _, attempts, gateway, _, _, memory_extraction_service = _service()
    gateway.generate_stream.side_effect = RuntimeError("provider unavailable")

    _, stream = service.stream_chat(ChatRequest(conversation_id=None, message="Hello"))
    with pytest.raises(RuntimeError, match="provider unavailable"):
        next(stream)

    failure = attempts.fail_generation_attempt.call_args
    assert failure.kwargs["error_code"] == "provider_error"
    assert failure.kwargs["partial_content"] is None
    attempts.complete_generation_attempt.assert_not_called()
    memory_extraction_service.process.assert_not_called()


def test_stream_failure_flushes_partial_output_to_attempt() -> None:
    """Verify provider failure retains chunks outside completed history.

    Raises:
        RuntimeError:
            Raised by the fake provider after yielding partial output.
    """

    service, _, attempts, gateway, _, _, memory_extraction_service = _service()

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

    failure = attempts.fail_generation_attempt.call_args
    assert failure.kwargs["partial_content"] == "Partial"
    attempts.complete_generation_attempt.assert_not_called()
    memory_extraction_service.process.assert_not_called()


def test_stream_consumer_closure_marks_attempt_interrupted() -> None:
    """Verify generator closure flushes partial output as interrupted."""

    service, _, attempts, _, _, _, memory_extraction_service = _service()
    _, stream = service.stream_chat(ChatRequest(conversation_id=None, message="Hello"))

    assert next(stream) == "Hello "
    stream.close()

    interruption = attempts.interrupt_generation_attempt.call_args
    assert interruption.kwargs["partial_content"] == "Hello "
    attempts.complete_generation_attempt.assert_not_called()
    memory_extraction_service.process.assert_not_called()


def test_stream_consumer_closure_before_output_marks_attempt_interrupted() -> None:
    """Verify an unconsumed prepared stream can still be closed durably."""

    service, _, attempts, gateway, _, _, _ = _service()
    _, stream = service.stream_chat(ChatRequest(conversation_id=None, message="Hello"))

    stream.close()

    attempts.interrupt_generation_attempt.assert_called_once()
    gateway.generate_stream.assert_not_called()


def test_stale_streaming_attempt_is_reconciled_as_interrupted() -> None:
    """Verify resuming a conversation terminates an unowned stream."""

    service, conversations, attempts, _, registry, _, _ = _service()
    conversation = conversations.get_or_create_conversation.return_value
    stale = _attempt(conversation.id, registry.get_model.return_value).start(
        at=datetime.now(UTC)
    )
    attempts.get_open_generation_attempt.return_value = stale

    service.reconcile_generation_attempts(conversation.id)

    attempts.interrupt_generation_attempt.assert_called_once()
    attempts.begin_generation_attempt.assert_not_called()
