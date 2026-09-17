from __future__ import annotations

import logging
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from chat_buddy.chat.application.schemas import (
    ChatRequest,
    ChatResponse,
    GenerationSelection,
    ModelOption,
    ProviderOption,
)
from chat_buddy.chat.application.service.conversation_service import ConversationService
from chat_buddy.chat.application.service.memory_service import MemoryService
from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    ContextBuilder,
    ConversationRecord,
    GenerationAttemptRecord,
    GenerationAttemptStatus,
    GenerationConfiguration,
    InvalidGenerationAttemptTransitionError,
    InvalidGenerationConfigurationError,
    ModelDescriptor,
    ModelId,
    ProviderId,
    ProviderRegistry,
    ResponseGatewayResolver,
    ResponseGenerator,
    TitleGenerator,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class _PreparedGeneration:
    """Validated state shared by synchronous and streaming generation."""

    conversation_id: UUID
    conversation_title: str | None
    user_message: str
    attempt: GenerationAttemptRecord
    model: ModelDescriptor
    configuration: GenerationConfiguration
    gateway: ResponseGenerator
    messages: list[ChatMessage]
    context: list[ChatMessage]
    is_first_exchange: bool


class ChatService:
    """Coordinate provider-neutral response generation and completed-turn effects."""

    def __init__(
        self,
        conversation_service: ConversationService,
        memory_service: MemoryService,
        context_builder: ContextBuilder,
        provider_registry: ProviderRegistry,
        response_gateway_resolver: ResponseGatewayResolver,
        title_generator: TitleGenerator,
    ) -> None:
        """Initialize the service.

        Args:
            conversation_service:
                Conversation and generation-attempt persistence service.
            memory_service:
                Persistent memory service.
            context_builder:
                Context window builder.
            provider_registry:
                Registry used to resolve models and effective configuration.
            response_gateway_resolver:
                Resolver for provider-specific response adapters.
            title_generator:
                Independently configured conversation-title generator.
        """

        self._conversation_service = conversation_service
        self._memory_service = memory_service
        self._context_builder = context_builder
        self._provider_registry = provider_registry
        self._response_gateway_resolver = response_gateway_resolver
        self._title_generator = title_generator
        self._active_attempt_ids: set[UUID] = set()

    def chat(self, request: ChatRequest) -> ChatResponse:
        """Generate, persist, and return one complete assistant response.

        Args:
            request:
                User chat request.

        Returns:
            Completed assistant response.
        """

        generation = self._prepare_generation(request, require_streaming=False)
        response = self._generate_complete_response(generation)

        logger.info(
            "Generated response for conversation %s.",
            generation.conversation_id,
        )
        return ChatResponse(
            conversation_id=generation.conversation_id,
            response=response,
        )

    def stream_chat(
        self,
        request: ChatRequest,
    ) -> tuple[UUID, Generator[str, None, None]]:
        """Prepare a turn and return its provider-neutral response stream.

        Args:
            request:
                User chat request.

        Returns:
            Conversation identifier and a response generator.
        """

        generation = self._prepare_generation(request, require_streaming=True)

        return generation.conversation_id, self._stream_generation(generation)

    def retry(self, attempt_id: UUID) -> ChatResponse:
        """Retry an incomplete attempt without duplicating its user message.

        Args:
            attempt_id:
                Identifier of the failed or interrupted attempt to retry.

        Returns:
            Completed assistant response from the new attempt.
        """

        generation = self._prepare_retry(attempt_id, require_streaming=False)
        response = self._generate_complete_response(generation)
        return ChatResponse(
            conversation_id=generation.conversation_id,
            response=response,
        )

    def stream_retry(self, attempt_id: UUID) -> tuple[UUID, Generator[str, None, None]]:
        """Retry an incomplete attempt as a provider-neutral response stream.

        Args:
            attempt_id:
                Identifier of the failed or interrupted attempt to retry.

        Returns:
            Conversation identifier and a new response generator.
        """

        generation = self._prepare_retry(attempt_id, require_streaming=True)
        return generation.conversation_id, self._stream_generation(generation)

    def reconcile_generation_attempts(self, conversation_id: UUID) -> None:
        """Interrupt unresolved attempts no longer owned by an active stream.

        Args:
            conversation_id:
                Identifier of the resumed conversation.
        """

        for attempt in self._conversation_service.get_unresolved_generation_attempts(
            conversation_id
        ):
            if attempt.id in self._active_attempt_ids:
                continue

            reconciled_at = max(
                timestamp
                for timestamp in (
                    datetime.now(UTC),
                    attempt.created_at,
                    attempt.started_at,
                )
                if timestamp is not None
            )
            if attempt.status is GenerationAttemptStatus.PENDING:
                self._conversation_service.begin_generation_attempt(
                    attempt.id,
                    at=reconciled_at,
                )
            self._conversation_service.interrupt_generation_attempt(
                attempt.id,
                at=reconciled_at,
                partial_content=attempt.partial_content,
            )
            logger.info(
                "Reconciled stale generation attempt %s as interrupted.",
                attempt.id,
            )

    def get_generation_selection(
        self, conversation_id: UUID | None
    ) -> GenerationSelection:
        """Return application-owned provider choices and current defaults.

        Args:
            conversation_id:
                Selected conversation, or ``None`` for a new conversation.

        Returns:
            Available choices and the selection to display.
        """

        selected = (
            self._conversation_service.get_conversation(conversation_id)
            if conversation_id is not None
            else None
        )
        if (
            selected is None
            or selected.provider_id is None
            or selected.model_id is None
        ):
            model = self._provider_registry.get_default_model()
            configuration = (
                selected.requested_generation_configuration
                if selected is not None
                else GenerationConfiguration()
            )
        else:
            model = self._provider_registry.get_model(
                selected.provider_id, selected.model_id
            )
            configuration = selected.requested_generation_configuration

        providers = tuple(
            ProviderOption(id=item.id, display_name=item.display_name)
            for item in self._provider_registry.list_providers()
        )
        models = tuple(
            ModelOption(
                provider_id=item.provider_id,
                id=item.id,
                display_name=item.display_name,
                supported_generation_parameters=item.supported_generation_parameters,
            )
            for item in self._provider_registry.list_models()
        )
        return GenerationSelection(
            providers=providers,
            models=models,
            provider_id=model.provider_id,
            model_id=model.id,
            configuration=configuration,
        )

    def update_generation_selection(
        self,
        conversation_id: UUID | None,
        provider_id: ProviderId,
        model_id: ModelId,
        configuration: GenerationConfiguration,
    ) -> UUID:
        """Validate and persist defaults used at the next generation boundary.

        Args:
            conversation_id:
                Existing conversation, or ``None`` to create one.
            provider_id:
                Selected provider identifier.
            model_id:
                Selected provider-local model identifier.
            configuration:
                Requested provider-neutral generation configuration.

        Returns:
            Identifier of the updated conversation.

        Raises:
            LookupError:
                If an existing conversation no longer exists.
        """

        model = self._provider_registry.get_model(provider_id, model_id)
        self._provider_registry.resolve_generation_configuration(model, configuration)
        conversation: ConversationRecord | None
        if conversation_id is None:
            conversation = self._conversation_service.create_conversation()
        else:
            conversation = self._conversation_service.get_conversation(conversation_id)
            if conversation is None:
                raise LookupError(f"Conversation {conversation_id} does not exist.")
        updated = self._conversation_service.update_generation_defaults(
            conversation.id,
            provider_id,
            model_id,
            configuration,
        )
        if updated is None:
            raise LookupError(f"Conversation {conversation.id} does not exist.")
        return updated.id

    def get_recoverable_generation_attempts(
        self, conversation_id: UUID
    ) -> tuple[GenerationAttemptRecord, ...]:
        """Return latest incomplete attempts that have no successful retry.

        Args:
            conversation_id:
                Identifier of the resumed conversation.

        Returns:
            Latest failed or interrupted attempt for each unresolved user message.
        """

        self.reconcile_generation_attempts(conversation_id)
        attempts = self._conversation_service.get_generation_attempts(conversation_id)
        completed_sources = {
            attempt.source_user_message_id
            for attempt in attempts
            if attempt.status is GenerationAttemptStatus.COMPLETED
        }
        recoverable_by_source: dict[UUID, GenerationAttemptRecord] = {}
        for attempt in attempts:
            if (
                attempt.source_user_message_id not in completed_sources
                and attempt.status
                in {
                    GenerationAttemptStatus.FAILED,
                    GenerationAttemptStatus.INTERRUPTED,
                }
            ):
                recoverable_by_source[attempt.source_user_message_id] = attempt
        return tuple(recoverable_by_source.values())

    def _stream_generation(
        self, generation: _PreparedGeneration
    ) -> Generator[str, None, None]:
        """Create a tracked stream that persists every terminal outcome.

        Args:
            generation:
                Prepared generation state.

        Returns:
            Tracked assistant-response generator.
        """

        self._active_attempt_ids.add(generation.attempt.id)

        def _generate() -> Generator[str, None, None]:
            """Stream chunks and atomically persist the terminal outcome.

            Yields:
                Successive assistant-response chunks.
            """

            accumulated_response = ""
            started = False
            try:
                self._begin_generation(generation.attempt)
                started = True
                # Prime the generator to establish active ownership before it is
                # returned. The private empty yield is consumed below, allowing
                # close() to persist interruption even before provider output.
                yield ""
                for chunk in generation.gateway.generate_stream(
                    generation.context,
                    generation.model.id,
                    generation.configuration,
                ):
                    accumulated_response += chunk
                    yield chunk

            except GeneratorExit:
                if started:
                    self._interrupt_generation(generation, accumulated_response)
                raise
            except Exception:
                if started:
                    self._fail_generation(generation, accumulated_response)
                logger.exception(
                    "Error during streaming for conversation %s.",
                    generation.conversation_id,
                )
                raise
            else:
                self._complete_generation(generation, accumulated_response)
                logger.info(
                    "Completed streaming response for conversation %s.",
                    generation.conversation_id,
                )
            finally:
                self._active_attempt_ids.discard(generation.attempt.id)

        stream = _generate()
        next(stream)
        return stream

    def _prepare_generation(
        self,
        request: ChatRequest,
        *,
        require_streaming: bool,
    ) -> _PreparedGeneration:
        """Resolve and persist immutable generation inputs before invocation.

        Args:
            request:
                User chat request.
            require_streaming:
                Whether the selected model must support streaming.

        Returns:
            Validated generation state and provider adapter.

        Raises:
            InvalidGenerationConfigurationError:
                If a streaming request selects a non-streaming model.
            ValueError:
                If persisted provider and model selection is incomplete.
        """

        if request.conversation_id is not None:
            self.reconcile_generation_attempts(request.conversation_id)
        conversation = self._conversation_service.get_or_create_conversation(
            conversation_id=request.conversation_id,
        )
        model, configuration, gateway = self._resolve_generation_defaults(
            conversation, require_streaming=require_streaming
        )
        attempt = self._conversation_service.start_generation_attempt(
            conversation.id,
            request.message,
            model.provider_id,
            model.id,
            configuration,
        )
        return self._build_prepared_generation(
            conversation_id=conversation.id,
            conversation_title=conversation.title,
            user_message=request.message,
            attempt=attempt,
            model=model,
            configuration=configuration,
            gateway=gateway,
        )

    def _resolve_generation_defaults(
        self,
        conversation: ConversationRecord,
        *,
        require_streaming: bool,
    ) -> tuple[ModelDescriptor, GenerationConfiguration, ResponseGenerator]:
        """Resolve validated model, configuration, and response adapter.

        Args:
            conversation:
                Conversation record containing requested defaults.
            require_streaming:
                Whether the selected model must support streaming.

        Returns:
            Selected model, effective configuration, and response adapter.

        Raises:
            InvalidGenerationConfigurationError:
                If streaming is requested for a non-streaming model.
            ValueError:
                If the persisted selection is incomplete.
        """

        selected = conversation
        provider_id = selected.provider_id
        model_id = selected.model_id
        requested = selected.requested_generation_configuration
        if provider_id is None and model_id is None:
            model = self._provider_registry.get_default_model()
            updated = self._conversation_service.update_generation_defaults(
                selected.id,
                model.provider_id,
                model.id,
                requested,
            )
            if updated is not None:
                selected = updated
                requested = updated.requested_generation_configuration
        elif provider_id is None or model_id is None:
            raise ValueError(
                "Conversation provider and model must be selected together."
            )
        else:
            model = self._provider_registry.get_model(
                provider_id,
                model_id,
            )

        if require_streaming and not model.supports_streaming:
            raise InvalidGenerationConfigurationError(
                f"Model '{model.id}' does not support streaming."
            )

        configuration = self._provider_registry.resolve_generation_configuration(
            model,
            requested,
        )
        gateway = self._response_gateway_resolver.resolve(model.provider_id)
        return model, configuration, gateway

    def _prepare_retry(
        self, attempt_id: UUID, *, require_streaming: bool
    ) -> _PreparedGeneration:
        """Resolve current defaults and create a retry for one source message.

        Args:
            attempt_id:
                Identifier of the incomplete attempt to retry.
            require_streaming:
                Whether the retry requires streaming support.

        Returns:
            Validated retry generation state.

        Raises:
            LookupError:
                If the attempt, conversation, or source message does not exist.
            InvalidGenerationAttemptTransitionError:
                If the attempt is not failed or interrupted.
        """

        source = self._conversation_service.get_generation_attempt(attempt_id)
        if source is None:
            raise LookupError(f"Generation attempt {attempt_id} does not exist.")
        if source.status not in {
            GenerationAttemptStatus.FAILED,
            GenerationAttemptStatus.INTERRUPTED,
        }:
            raise InvalidGenerationAttemptTransitionError(
                "Only a failed or interrupted attempt can be retried."
            )
        self.reconcile_generation_attempts(source.conversation_id)
        conversation = self._conversation_service.get_conversation(
            source.conversation_id
        )
        if conversation is None:
            raise LookupError(f"Conversation {source.conversation_id} does not exist.")
        source_message = self._conversation_service.get_message(
            source.source_user_message_id
        )
        if source_message is None:
            raise LookupError(
                f"Source message {source.source_user_message_id} does not exist."
            )
        model, configuration, gateway = self._resolve_generation_defaults(
            conversation, require_streaming=require_streaming
        )
        retry = self._conversation_service.retry_generation_attempt(
            source.id,
            model.provider_id,
            model.id,
            configuration,
        )
        return self._build_prepared_generation(
            conversation_id=conversation.id,
            conversation_title=conversation.title,
            user_message=source_message.content,
            attempt=retry,
            model=model,
            configuration=configuration,
            gateway=gateway,
        )

    def _build_prepared_generation(
        self,
        *,
        conversation_id: UUID,
        conversation_title: str | None,
        user_message: str,
        attempt: GenerationAttemptRecord,
        model: ModelDescriptor,
        configuration: GenerationConfiguration,
        gateway: ResponseGenerator,
    ) -> _PreparedGeneration:
        """Build provider context and shared immutable generation state.

        Args:
            conversation_id:
                Identifier of the target conversation.
            conversation_title:
                Existing title, if any.
            user_message:
                Source user-message content.
            attempt:
                Newly persisted pending attempt.
            model:
                Selected model descriptor.
            configuration:
                Effective provider-neutral generation configuration.
            gateway:
                Resolved response adapter.

        Returns:
            Prepared generation state.
        """

        messages = self._conversation_service.get_messages(conversation_id)
        is_first_exchange = len(messages) == 1
        messages_with_memories = self._memory_service.inject_memories(messages)
        context = self._context_builder.build_context(messages_with_memories, model)

        logger.info(
            "Prepared generation attempt %s for conversation %s with %s/%s.",
            attempt.id,
            conversation_id,
            model.provider_id,
            model.id,
        )
        return _PreparedGeneration(
            conversation_id=conversation_id,
            conversation_title=conversation_title,
            user_message=user_message,
            attempt=attempt,
            model=model,
            configuration=configuration,
            gateway=gateway,
            messages=messages,
            context=context,
            is_first_exchange=is_first_exchange,
        )

    def _generate_complete_response(self, generation: _PreparedGeneration) -> str:
        """Invoke a synchronous provider and persist its terminal outcome.

        Args:
            generation:
                Prepared generation state.

        Returns:
            Completed assistant response.
        """

        self._active_attempt_ids.add(generation.attempt.id)
        try:
            self._begin_generation(generation.attempt)
            try:
                response = generation.gateway.generate(
                    generation.context,
                    generation.model.id,
                    generation.configuration,
                )
            except Exception:
                self._fail_generation(generation)
                logger.exception(
                    "Error during generation for conversation %s.",
                    generation.conversation_id,
                )
                raise

            self._complete_generation(generation, response)
            return response
        finally:
            self._active_attempt_ids.discard(generation.attempt.id)

    def _fail_generation(
        self, generation: _PreparedGeneration, partial_content: str = ""
    ) -> None:
        """Persist safe failure information without masking provider errors.

        Args:
            generation:
                Prepared generation state.
            partial_content:
                Complete response content accumulated before failure.
        """

        try:
            self._conversation_service.fail_generation_attempt(
                generation.attempt.id,
                error_code="provider_error",
                error_detail="The response provider could not complete the request.",
                partial_content=partial_content or None,
                at=datetime.now(UTC),
            )
        except Exception:
            logger.exception(
                "Failed to persist provider failure for attempt %s.",
                generation.attempt.id,
            )

    def _interrupt_generation(
        self, generation: _PreparedGeneration, partial_content: str
    ) -> None:
        """Persist consumer cancellation and any available partial output.

        Args:
            generation:
                Prepared generation state.
            partial_content:
                Complete response content accumulated before cancellation.
        """

        self._conversation_service.interrupt_generation_attempt(
            generation.attempt.id,
            partial_content=partial_content or None,
            at=datetime.now(UTC),
        )

    def _begin_generation(self, attempt: GenerationAttemptRecord) -> None:
        """Persist the transition immediately before provider invocation.

        Args:
            attempt:
                Pending generation attempt.
        """

        self._conversation_service.begin_generation_attempt(
            attempt.id,
            at=datetime.now(UTC),
        )

    def _complete_generation(
        self,
        generation: _PreparedGeneration,
        response: str,
    ) -> None:
        """Commit a response before running completed-turn side effects.

        Args:
            generation:
                Prepared generation state.
            response:
                Complete assistant response.
        """

        self._conversation_service.complete_generation_attempt(
            generation.attempt.id,
            response,
            at=datetime.now(UTC),
        )
        self._memory_service.extract_memories(generation.messages)
        if generation.is_first_exchange and not generation.conversation_title:
            self._title_conversation(
                conversation_id=generation.conversation_id,
                user_message=generation.user_message,
                assistant_message=response,
            )

    def _title_conversation(
        self,
        conversation_id: UUID,
        user_message: str,
        assistant_message: str,
    ) -> None:
        """Generate and persist a title for a first exchange.

        Args:
            conversation_id:
                Unique conversation identifier.
            user_message:
                First user message in the conversation.
            assistant_message:
                Assistant reply for the first exchange.
        """

        title = ""
        try:
            title = self._sanitize_title(
                self._title_generator.generate_title(
                    [
                        ChatMessage(role=ChatRole.USER, content=user_message),
                        ChatMessage(
                            role=ChatRole.ASSISTANT,
                            content=assistant_message,
                        ),
                    ]
                )
            )
        except Exception:
            logger.exception(
                "Failed to generate title for conversation %s.",
                conversation_id,
            )

        if not title:
            title = self._build_fallback_title(user_message)

        try:
            updated = self._conversation_service.rename_conversation(
                conversation_id=conversation_id,
                title=title,
            )
            if updated:
                logger.info(
                    "Set conversation %s title to '%s'.",
                    conversation_id,
                    title,
                )
            else:
                logger.warning(
                    "Conversation %s title was not updated.",
                    conversation_id,
                )
        except Exception:
            logger.exception(
                "Failed to persist conversation title for %s.",
                conversation_id,
            )

    def _sanitize_title(self, title: str) -> str:
        """Normalize a generated title for persistence.

        Args:
            title:
                Generated title text.

        Returns:
            Cleaned title text.
        """

        cleaned = title.replace("\n", " ").strip()
        cleaned = cleaned.strip('"').strip("'").strip()
        cleaned = " ".join(cleaned.split())
        return self._auto_ellipsis(cleaned)

    def _build_fallback_title(self, user_message: str) -> str:
        """Build a deterministic fallback title.

        Args:
            user_message:
                First user message in the conversation.

        Returns:
            Fallback title text.
        """

        cleaned = " ".join(user_message.split()).strip('"').strip("'")
        if not cleaned:
            return "New conversation"
        return self._auto_ellipsis(cleaned)

    def _auto_ellipsis(self, text: str) -> str:
        """Clip given text and append ellipsis when necessary.

        Args:
            text:
                Given text.

        Returns:
            Original or clipped text ending with ellipsis.
        """

        if len(text) > 50:
            return f"{text[:47].rstrip()}..."
        return text
