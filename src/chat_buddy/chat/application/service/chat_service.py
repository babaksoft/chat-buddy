from __future__ import annotations

import logging
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from chat_buddy.chat.application.schemas import ChatRequest, ChatResponse
from chat_buddy.chat.application.service.conversation_service import ConversationService
from chat_buddy.chat.application.service.memory_service import MemoryService
from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    ContextBuilder,
    GenerationAttemptRecord,
    GenerationConfiguration,
    InvalidGenerationConfigurationError,
    ModelDescriptor,
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
    request: ChatRequest
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

    def chat(self, request: ChatRequest) -> ChatResponse:
        """Generate, persist, and return one complete assistant response.

        Args:
            request:
                User chat request.

        Returns:
            Completed assistant response.
        """

        generation = self._prepare_generation(request, require_streaming=False)
        self._begin_generation(generation.attempt)
        response = generation.gateway.generate(
            generation.context,
            generation.model.id,
            generation.configuration,
        )
        self._complete_generation(generation, response)

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

        def _generate() -> Generator[str, None, None]:
            """Stream chunks and atomically commit the completed response.

            Yields:
                Successive assistant-response chunks.
            """

            self._begin_generation(generation.attempt)
            accumulated_response = ""
            try:
                for chunk in generation.gateway.generate_stream(
                    generation.context,
                    generation.model.id,
                    generation.configuration,
                ):
                    accumulated_response += chunk
                    yield chunk

            except Exception:
                logger.exception(
                    "Error during streaming for conversation %s.",
                    generation.conversation_id,
                )
                raise

            self._complete_generation(generation, accumulated_response)
            logger.info(
                "Completed streaming response for conversation %s.",
                generation.conversation_id,
            )

        return generation.conversation_id, _generate()

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

        conversation = self._conversation_service.get_or_create_conversation(
            conversation_id=request.conversation_id,
        )
        if conversation.provider_id is None and conversation.model_id is None:
            model = self._provider_registry.get_default_model()
            updated = self._conversation_service.update_generation_defaults(
                conversation.id,
                model.provider_id,
                model.id,
                conversation.requested_generation_configuration,
            )
            if updated is not None:
                conversation = updated
        elif conversation.provider_id is None or conversation.model_id is None:
            raise ValueError(
                "Conversation provider and model must be selected together."
            )
        else:
            model = self._provider_registry.get_model(
                conversation.provider_id,
                conversation.model_id,
            )

        if require_streaming and not model.supports_streaming:
            raise InvalidGenerationConfigurationError(
                f"Model '{model.id}' does not support streaming."
            )

        configuration = self._provider_registry.resolve_generation_configuration(
            model,
            conversation.requested_generation_configuration,
        )
        gateway = self._response_gateway_resolver.resolve(model.provider_id)
        attempt = self._conversation_service.start_generation_attempt(
            conversation.id,
            request.message,
            model.provider_id,
            model.id,
            configuration,
        )
        messages = self._conversation_service.get_messages(conversation.id)
        is_first_exchange = len(messages) == 1
        messages_with_memories = self._memory_service.inject_memories(messages)
        context = self._context_builder.build_context(messages_with_memories, model)

        logger.info(
            "Prepared generation attempt %s for conversation %s with %s/%s.",
            attempt.id,
            conversation.id,
            model.provider_id,
            model.id,
        )
        return _PreparedGeneration(
            conversation_id=conversation.id,
            conversation_title=conversation.title,
            request=request,
            attempt=attempt,
            model=model,
            configuration=configuration,
            gateway=gateway,
            messages=messages,
            context=context,
            is_first_exchange=is_first_exchange,
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
                user_message=generation.request.message,
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
