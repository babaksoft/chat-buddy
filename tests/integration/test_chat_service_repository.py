from collections.abc import Iterator
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from chat_buddy.chat.application.schemas import ChatRequest
from chat_buddy.chat.application.service import (
    ChatService,
    ConversationService,
    GenerationAttemptService,
)
from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    ContextAssemblyResult,
    GenerationAttemptStatus,
    GenerationConfiguration,
    GenerationParameter,
    ModelDescriptor,
    ModelId,
    ProviderDescriptor,
    ProviderId,
)
from chat_buddy.chat.infrastructure.db.models import GenerationAttempt
from chat_buddy.chat.infrastructure.db.repositories import (
    ConversationRepository,
    GenerationAttemptRepository,
)
from chat_buddy.chat.infrastructure.llm.provider_registry import (
    StaticProviderRegistry,
    StaticResponseGatewayResolver,
)

PROVIDER_ID = ProviderId("test-provider")
SECOND_PROVIDER_ID = ProviderId("second-provider")
FIRST_MODEL_ID = ModelId("first-model")
SECOND_MODEL_ID = ModelId("second-model")
SECOND_PROVIDER_MODEL_ID = ModelId("second-provider-model")


class FakeGateway:
    """Response and title test adapter with recorded generation inputs."""

    def __init__(self, title: str = "Conversation title") -> None:
        """Initialize the adapter.

        Args:
            title:
                Title returned by the utility capability.
        """

        self.title = title
        self.last_messages: list[ChatMessage] = []

    def generate(
        self,
        messages: list[ChatMessage],
        model_id: ModelId,
        configuration: GenerationConfiguration,
    ) -> str:
        """Return a deterministic complete response.

        Args:
            messages:
                Prepared conversation context.
            model_id:
                Selected model identifier.
            configuration:
                Effective generation configuration.

        Returns:
            Deterministic assistant response.
        """

        self.last_messages = messages
        return f"Response from {model_id}."

    def generate_stream(
        self,
        messages: list[ChatMessage],
        model_id: ModelId,
        configuration: GenerationConfiguration,
    ) -> Iterator[str]:
        """Yield a deterministic response in chunks.

        Args:
            messages:
                Prepared conversation context.
            model_id:
                Selected model identifier.
            configuration:
                Effective generation configuration.

        Yields:
            Deterministic assistant-response chunks.
        """

        self.last_messages = messages
        yield "Streamed "
        yield f"from {model_id}."

    def generate_title(self, messages: list[ChatMessage]) -> str:
        """Return the configured conversation title.

        Args:
            messages:
                Completed first exchange.

        Returns:
            Configured title text.
        """

        return self.title


class RecoveringGateway(FakeGateway):
    """Fake gateway whose synchronous response can fail and recover."""

    def __init__(self) -> None:
        """Initialize the gateway in its failing state."""

        super().__init__()
        self.should_fail = True

    def generate(
        self,
        messages: list[ChatMessage],
        model_id: ModelId,
        configuration: GenerationConfiguration,
    ) -> str:
        """Fail while configured to do so, otherwise return a response.

        Args:
            messages:
                Prepared conversation context.
            model_id:
                Selected model identifier.
            configuration:
                Effective generation configuration.

        Returns:
            Deterministic assistant response after recovery.

        Raises:
            RuntimeError:
                If the gateway is still configured to fail.
        """

        if self.should_fail:
            raise RuntimeError("provider unavailable")

        return super().generate(messages, model_id, configuration)


def _model(
    model_id: ModelId,
    provider_id: ProviderId = PROVIDER_ID,
) -> ModelDescriptor:
    """Create a selectable integration-test model.

    Args:
        model_id:
            Provider-local model identifier.
        provider_id:
            Provider that owns the model.

    Returns:
        Model descriptor with deterministic defaults.
    """

    return ModelDescriptor(
        provider_id=provider_id,
        id=model_id,
        display_name=str(model_id),
        context_window_tokens=4_096,
        supports_streaming=True,
        supported_generation_parameters=frozenset({GenerationParameter.TEMPERATURE}),
        default_generation_configuration=GenerationConfiguration(temperature=0.2),
        token_counter=Mock(),
        default_output_token_reserve=512,
    )


def _build_service(
    session: Session,
    gateway: FakeGateway,
    *,
    memory_extraction_service: Mock | None = None,
    second_provider_gateway: FakeGateway | None = None,
) -> tuple[ChatService, ConversationService, ConversationRepository]:
    """Compose provider-neutral Chat services around a real repository.

    Args:
        session:
            Database session used for persistence.
        gateway:
            Fake response and title adapter.
        memory_extraction_service:
            Optional memory-extraction test double.
        second_provider_gateway:
            Optional independently composed second response provider.

    Returns:
        Chat service, conversation service, and repository.
    """

    providers = [ProviderDescriptor(PROVIDER_ID, "Test provider")]
    models = [_model(FIRST_MODEL_ID), _model(SECOND_MODEL_ID)]
    gateways = {PROVIDER_ID: gateway}
    if second_provider_gateway is not None:
        providers.append(ProviderDescriptor(SECOND_PROVIDER_ID, "Second provider"))
        models.append(_model(SECOND_PROVIDER_MODEL_ID, SECOND_PROVIDER_ID))
        gateways[SECOND_PROVIDER_ID] = second_provider_gateway

    registry = StaticProviderRegistry(
        providers=providers,
        models=models,
        default_provider_id=PROVIDER_ID,
        default_model_id=FIRST_MODEL_ID,
    )
    resolver = StaticResponseGatewayResolver(gateways)
    repository = ConversationRepository(session)
    attempt_repository = GenerationAttemptRepository(session)
    conversation_service = ConversationService(repository)
    attempt_service = GenerationAttemptService(attempt_repository)
    extraction = memory_extraction_service or Mock()
    context_assembler = Mock()
    context_assembler.assemble.side_effect = (
        lambda conversation_id, current, model, configuration: ContextAssemblyResult(
            messages=(current,),
            prompt_tokens=1,
            prompt_capacity=model.context_window_tokens,
        )
    )
    return (
        ChatService(
            conversation_service=conversation_service,
            generation_attempt_service=attempt_service,
            memory_extraction_service=extraction,
            context_assembler=context_assembler,
            provider_registry=registry,
            response_gateway_resolver=resolver,
            title_generator=gateway,
        ),
        conversation_service,
        repository,
    )


def test_new_conversation_completes_with_default_model_provenance(
    session: Session,
) -> None:
    """Verify a new conversation persists response and immutable provenance.

    Args:
        session:
            Isolated database session.
    """

    gateway = FakeGateway()
    service, conversations, repository = _build_service(session, gateway)

    response = service.chat(ChatRequest(conversation_id=None, message="Hello"))

    messages = conversations.get_messages(response.conversation_id)
    attempts = list(session.scalars(select(GenerationAttempt)))
    persisted_conversation = repository.get_conversation(response.conversation_id)
    assert [message.role for message in messages] == [ChatRole.USER, ChatRole.ASSISTANT]
    assert messages[1].content == "Response from first-model."
    assert len(attempts) == 1
    assert attempts[0].status is GenerationAttemptStatus.COMPLETED
    assert attempts[0].provider_id == "test-provider"
    assert attempts[0].model_id == "first-model"
    assert attempts[0].effective_configuration["temperature"] == 0.2
    assert attempts[0].assistant_message_id is not None
    assert persisted_conversation is not None
    assert persisted_conversation.model_id == FIRST_MODEL_ID


def test_resumed_conversation_streams_through_persisted_selection(
    session: Session,
) -> None:
    """Verify streaming resumes with persisted model and requested settings.

    Args:
        session:
            Isolated database session.
    """

    gateway = FakeGateway()
    service, conversations, repository = _build_service(session, gateway)
    conversation = repository.create_conversation(
        provider_id=PROVIDER_ID,
        model_id=SECOND_MODEL_ID,
        requested_generation_configuration=GenerationConfiguration(temperature=0.7),
    )

    conversation_id, stream = service.stream_chat(
        ChatRequest(conversation_id=conversation.id, message="Continue")
    )

    assert conversation_id == conversation.id
    assert list(stream) == ["Streamed ", "from second-model."]
    assert conversations.get_messages(conversation.id)[1].content == (
        "Streamed from second-model."
    )
    attempt = session.scalar(select(GenerationAttempt))
    assert attempt is not None
    assert attempt.status is GenerationAttemptStatus.COMPLETED
    assert attempt.model_id == "second-model"
    assert attempt.effective_configuration["temperature"] == 0.7


def test_composed_second_provider_is_selectable_and_streams(
    session: Session,
) -> None:
    """Verify a second provider works without changing application services.

    Args:
        session:
            Isolated database session.
    """

    second_gateway = FakeGateway()
    service, conversations, repository = _build_service(
        session,
        FakeGateway(),
        second_provider_gateway=second_gateway,
    )
    conversation = repository.create_conversation()
    service.update_generation_selection(
        conversation.id,
        SECOND_PROVIDER_ID,
        SECOND_PROVIDER_MODEL_ID,
        GenerationConfiguration(temperature=0.6),
    )

    conversation_id, stream = service.stream_chat(
        ChatRequest(conversation.id, "Use the second provider")
    )

    assert conversation_id == conversation.id
    assert list(stream) == ["Streamed ", "from second-provider-model."]
    assert conversations.get_messages(conversation.id)[1].content == (
        "Streamed from second-provider-model."
    )
    attempt = session.scalar(select(GenerationAttempt))
    assert attempt is not None
    assert attempt.provider_id == "second-provider"
    assert attempt.model_id == "second-provider-model"
    assert attempt.effective_configuration["temperature"] == 0.6


def test_model_change_affects_next_attempt_without_rewriting_provenance(
    session: Session,
) -> None:
    """Verify selection changes apply only at the next attempt boundary.

    Args:
        session:
            Isolated database session.
    """

    service, conversations, repository = _build_service(session, FakeGateway())
    conversation = repository.create_conversation(
        provider_id=PROVIDER_ID,
        model_id=FIRST_MODEL_ID,
    )
    service.chat(ChatRequest(conversation.id, "First turn"))
    conversations.update_generation_defaults(
        conversation.id,
        PROVIDER_ID,
        SECOND_MODEL_ID,
        GenerationConfiguration(temperature=0.8),
    )
    service.chat(ChatRequest(conversation.id, "Second turn"))

    attempts = list(
        session.scalars(
            select(GenerationAttempt).order_by(GenerationAttempt.created_at)
        )
    )
    assert [attempt.model_id for attempt in attempts] == [
        "first-model",
        "second-model",
    ]
    assert attempts[0].effective_configuration["temperature"] == 0.2
    assert attempts[1].effective_configuration["temperature"] == 0.8


def test_title_generation_runs_after_completed_attempt(
    session: Session,
) -> None:
    """Verify successful first exchange retains existing auto-title behavior.

    Args:
        session:
            Isolated database session.
    """

    service, _, repository = _build_service(
        session,
        FakeGateway(title="Launch planning"),
    )

    response = service.chat(ChatRequest(None, "Plan the launch"))

    conversation = repository.get_conversation(response.conversation_id)
    attempt = session.scalar(select(GenerationAttempt))
    assert attempt is not None
    assert attempt.status is GenerationAttemptStatus.COMPLETED
    assert conversation is not None
    assert conversation.title == "Launch planning"


def test_multiple_completed_turns_remain_normal_conversation_history(
    session: Session,
) -> None:
    """Verify lifecycle routing preserves ordinary multi-turn history.

    Args:
        session:
            Isolated database session.
    """

    service, conversations, repository = _build_service(session, FakeGateway())
    conversation = repository.create_conversation()

    service.chat(ChatRequest(conversation.id, "First"))
    service.chat(ChatRequest(conversation.id, "Second"))

    messages = conversations.get_messages(conversation.id)
    assert [message.role for message in messages] == [
        ChatRole.USER,
        ChatRole.ASSISTANT,
        ChatRole.USER,
        ChatRole.ASSISTANT,
    ]


def test_successful_retry_reuses_user_message_and_adds_one_assistant(
    session: Session,
) -> None:
    """Verify retry recovery creates one response without duplicate input.

    Args:
        session:
            Isolated database session.
    """

    gateway = RecoveringGateway()
    extraction = Mock()
    service, conversations, _ = _build_service(
        session,
        gateway,
        memory_extraction_service=extraction,
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.chat(ChatRequest(None, "Recover this turn"))
    failed = session.scalar(select(GenerationAttempt))
    assert failed is not None
    assert failed.status is GenerationAttemptStatus.FAILED

    conversations.edit_unmatched_user_message(
        failed.conversation_id,
        "Recover this edited turn",
    )
    gateway.should_fail = False
    response = service.retry(failed.id)

    messages = conversations.get_messages(response.conversation_id)
    attempts = list(
        session.scalars(
            select(GenerationAttempt).order_by(GenerationAttempt.created_at)
        )
    )
    assert [message.role for message in messages] == [
        ChatRole.USER,
        ChatRole.ASSISTANT,
    ]
    assert [message.content for message in messages].count(
        "Recover this edited turn"
    ) == 1
    assert [attempt.status for attempt in attempts] == [
        GenerationAttemptStatus.FAILED,
        GenerationAttemptStatus.COMPLETED,
    ]
    assert attempts[0].source_user_message_id == attempts[1].source_user_message_id
    extraction.process.assert_called_once()
    extracted_turn = extraction.process.call_args.args[0]
    assert extracted_turn.attempt_id == attempts[1].id
    assert extracted_turn.user_content == "Recover this edited turn"
    assert extracted_turn.assistant_content == f"Response from {FIRST_MODEL_ID}."
    assert [message.content for message in gateway.last_messages].count(
        "Recover this edited turn"
    ) == 1


def test_failed_retry_remains_outside_completed_history(session: Session) -> None:
    """Verify another provider failure creates no assistant message.

    Args:
        session:
            Isolated database session.
    """

    gateway = RecoveringGateway()
    service, conversations, _ = _build_service(session, gateway)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.chat(ChatRequest(None, "Still failing"))
    failed = session.scalar(select(GenerationAttempt))
    assert failed is not None

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.retry(failed.id)

    attempts = list(session.scalars(select(GenerationAttempt)))
    messages = conversations.get_messages(failed.conversation_id)
    assert len(attempts) == 2
    assert all(attempt.status is GenerationAttemptStatus.FAILED for attempt in attempts)
    assert [message.role for message in messages] == [ChatRole.USER]
