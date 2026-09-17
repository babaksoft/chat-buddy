import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from chat_buddy.chat.domain import (
    ChatRole,
    ConversationRecord,
    GenerationAttemptRecord,
    GenerationAttemptStatus,
    GenerationConfiguration,
    InvalidGenerationAttemptTransitionError,
    MessageRecord,
    ModelId,
    ProviderId,
)
from chat_buddy.chat.infrastructure.db.models import (
    Conversation,
    GenerationAttempt,
    Message,
)

logger = logging.getLogger(__name__)


class ConversationRepository:
    """Provides persistence for conversations, messages, and generation attempts."""

    def __init__(self, session: Session) -> None:
        """
        Initialize the repository.

        Args:
            session:
                SQLAlchemy session.
        """

        self._session = session

    def create_conversation(
        self,
        title: str | None = None,
        provider_id: ProviderId | None = None,
        model_id: ModelId | None = None,
        requested_generation_configuration: GenerationConfiguration | None = None,
    ) -> ConversationRecord:
        """
        Create and persist a new conversation.

        Args:
            title:
                Optional conversation title.
            provider_id:
                Optional selected response provider.
            model_id:
                Optional selected provider-local model.
            requested_generation_configuration:
                Optional provider-neutral defaults requested for future attempts.

        Returns:
            The newly created conversation.

        Raises:
            SQLAlchemyError:
                If conversation persistence fails.
        """

        try:
            conversation = Conversation(
                title=title,
                provider_id=str(provider_id) if provider_id is not None else None,
                model_id=str(model_id) if model_id is not None else None,
                requested_generation_configuration=self._configuration_to_dict(
                    requested_generation_configuration or GenerationConfiguration()
                ),
            )

            self._session.add(conversation)
            self._session.commit()
            self._session.refresh(conversation)

            logger.info(
                "Created conversation %s",
                conversation.id,
            )

            return self._to_conversation_record(conversation)

        except SQLAlchemyError:
            self._session.rollback()

            logger.exception("Failed to create conversation.")
            raise

    def update_generation_defaults(
        self,
        conversation_id: UUID,
        provider_id: ProviderId,
        model_id: ModelId,
        requested_configuration: GenerationConfiguration,
    ) -> ConversationRecord | None:
        """Persist the requested defaults for subsequent generation attempts.

        Args:
            conversation_id:
                Identifier of the conversation to update.
            provider_id:
                Selected response provider.
            model_id:
                Selected provider-local model.
            requested_configuration:
                Requested provider-neutral settings.

        Returns:
            The updated conversation, or ``None`` if it does not exist.

        Raises:
            SQLAlchemyError:
                If persistence fails.
        """

        try:
            conversation = self._session.get(Conversation, conversation_id)
            if conversation is None:
                return None

            conversation.provider_id = str(provider_id)
            conversation.model_id = str(model_id)
            conversation.requested_generation_configuration = (
                self._configuration_to_dict(requested_configuration)
            )
            self._session.commit()
            self._session.refresh(conversation)
            return self._to_conversation_record(conversation)

        except SQLAlchemyError:
            self._session.rollback()

            logger.exception(
                "Failed to update generation defaults for conversation %s.",
                conversation_id,
            )
            raise

    def get_conversation(
        self,
        conversation_id: UUID,
    ) -> ConversationRecord | None:
        """
        Retrieve a conversation by identifier.

        Args:
            conversation_id:
                Unique conversation identifier.

        Returns:
            The matching conversation if found,
            otherwise None.
        """

        conversation = self._session.get(
            Conversation,
            conversation_id,
        )

        logger.debug(
            "Retrieved conversation %s: found=%s",
            conversation_id,
            conversation is not None,
        )

        if conversation is None:
            return None

        return self._to_conversation_record(conversation)

    def get_conversations(
        self,
    ) -> list[ConversationRecord]:
        """
        Retrieve all conversations.

        Conversations are returned in descending order
        of last update time.

        Returns:
            List of conversations ordered by most
            recently updated first.
        """

        statement = select(Conversation).order_by(
            Conversation.updated_at.desc(),
        )

        conversations = list(self._session.scalars(statement))

        logger.debug(
            "Retrieved %d conversations.",
            len(conversations),
        )

        return [self._to_conversation_record(item) for item in conversations]

    def rename_conversation(
        self,
        conversation_id: UUID,
        title: str,
    ) -> bool:
        """
        Rename a conversation.

        Args:
            conversation_id:
                Unique conversation identifier.
            title:
                New conversation title.

        Returns:
            True if the conversation was found and renamed,
            otherwise False.

        Raises:
            SQLAlchemyError:
                If title persistence fails.
        """

        try:
            conversation = self._session.get(
                Conversation,
                conversation_id,
            )

            if conversation is None:
                logger.warning(
                    "Conversation %s not found for rename.",
                    conversation_id,
                )

                return False

            conversation.title = title
            self._session.commit()
            self._session.refresh(conversation)

            logger.info(
                "Renamed conversation %s.",
                conversation_id,
            )

            return True

        except SQLAlchemyError:
            self._session.rollback()

            logger.exception(
                "Failed to rename conversation %s.",
                conversation_id,
            )
            raise

    def add_message(
        self,
        conversation_id: UUID,
        role: ChatRole,
        content: str,
    ) -> MessageRecord:
        """
        Add a message to an existing conversation.

        Args:
            conversation_id:
                Target conversation identifier.
            role:
                Role of the message author.
            content:
                Message text content.

        Returns:
            The newly created message.

        Raises:
            SQLAlchemyError:
                If message persistence fails.
        """

        try:
            message = Message(
                conversation_id=conversation_id,
                role=role,
                content=content,
            )

            self._session.add(message)
            self._session.commit()
            self._session.refresh(message)

            logger.info(
                "Added %s message to conversation %s",
                role.value,
                conversation_id,
            )

            return self._to_message_record(message)

        except SQLAlchemyError:
            self._session.rollback()

            logger.exception(
                "Failed to add message to conversation %s",
                conversation_id,
            )
            raise

    def get_messages(
        self,
        conversation_id: UUID,
    ) -> list[MessageRecord]:
        """
        Retrieve messages belonging to a conversation.

        Messages are returned in chronological order.

        Args:
            conversation_id:
                Target conversation identifier.

        Returns:
            List of conversation messages ordered
            from oldest to newest.
        """

        statement = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(
                Message.created_at.asc(),
            )
        )

        messages = list(self._session.scalars(statement))

        logger.debug(
            "Retrieved %d messages from conversation %s",
            len(messages),
            conversation_id,
        )

        return [self._to_message_record(item) for item in messages]

    def get_message(self, message_id: UUID) -> MessageRecord | None:
        """Retrieve one persisted message by identifier.

        Args:
            message_id:
                Identifier of the message to retrieve.

        Returns:
            The matching message, or ``None`` when it does not exist.
        """

        message = self._session.get(Message, message_id)
        return self._to_message_record(message) if message is not None else None

    def start_generation_attempt(
        self,
        conversation_id: UUID,
        user_content: str,
        provider_id: ProviderId,
        model_id: ModelId,
        effective_configuration: GenerationConfiguration,
    ) -> GenerationAttemptRecord:
        """Atomically persist a source user message and pending attempt.

        Args:
            conversation_id:
                Identifier of the target conversation.
            user_content:
                Source user-message content.
            provider_id:
                Effective response provider.
            model_id:
                Effective provider-local model.
            effective_configuration:
                Validated effective generation settings.

        Returns:
            The persisted pending attempt.

        Raises:
            LookupError:
                If the conversation does not exist.
            SQLAlchemyError:
                If persistence fails.
        """

        if self._session.get(Conversation, conversation_id) is None:
            raise LookupError(f"Conversation {conversation_id} does not exist.")

        created_at = datetime.now(UTC)
        message_id = uuid4()
        attempt = GenerationAttemptRecord(
            id=uuid4(),
            conversation_id=conversation_id,
            source_user_message_id=message_id,
            provider_id=provider_id,
            model_id=model_id,
            effective_configuration=effective_configuration,
            status=GenerationAttemptStatus.PENDING,
            created_at=created_at,
        )
        message = Message(
            id=message_id,
            conversation_id=conversation_id,
            role=ChatRole.USER,
            content=user_content,
            created_at=created_at,
        )
        attempt_model = self._from_generation_attempt(attempt)

        try:
            self._session.add_all((message, attempt_model))
            self._session.commit()
            return attempt

        except SQLAlchemyError:
            self._session.rollback()

            logger.exception(
                "Failed to start generation attempt for conversation %s.",
                conversation_id,
            )
            raise

    def retry_generation_attempt(
        self,
        attempt_id: UUID,
        provider_id: ProviderId,
        model_id: ModelId,
        effective_configuration: GenerationConfiguration,
    ) -> GenerationAttemptRecord:
        """Create a pending retry that reuses an incomplete attempt's source.

        Args:
            attempt_id:
                Identifier of the failed or interrupted attempt to retry.
            provider_id:
                Effective response provider for the retry.
            model_id:
                Effective provider-local model for the retry.
            effective_configuration:
                Validated immutable generation settings for the retry.

        Returns:
            The newly persisted pending retry.

        Raises:
            LookupError:
                If the source attempt does not exist.
            InvalidGenerationAttemptTransitionError:
                If the source attempt is not incomplete.
            SQLAlchemyError:
                If persistence fails.
        """

        source = self._get_attempt_model(attempt_id)
        if source.status not in {
            GenerationAttemptStatus.FAILED,
            GenerationAttemptStatus.INTERRUPTED,
        }:
            raise InvalidGenerationAttemptTransitionError(
                "Only a failed or interrupted attempt can be retried."
            )

        retry = GenerationAttemptRecord(
            id=uuid4(),
            conversation_id=source.conversation_id,
            source_user_message_id=source.source_user_message_id,
            provider_id=provider_id,
            model_id=model_id,
            effective_configuration=effective_configuration,
            status=GenerationAttemptStatus.PENDING,
            created_at=datetime.now(UTC),
        )
        try:
            self._session.add(self._from_generation_attempt(retry))
            self._session.commit()
            return retry

        except SQLAlchemyError:
            self._session.rollback()
            logger.exception("Failed to retry generation attempt %s.", attempt_id)
            raise

    def begin_generation_attempt(
        self, attempt_id: UUID, *, at: datetime
    ) -> GenerationAttemptRecord:
        """Transition a pending attempt to streaming.

        Args:
            attempt_id:
                Identifier of the attempt to start.
            at:
                Time response streaming started.

        Returns:
            The persisted streaming attempt.

        Raises:
            LookupError:
                If the attempt does not exist.
            InvalidGenerationAttemptTransitionError:
                If the attempt is not pending or the timestamp is invalid.
            SQLAlchemyError:
                If persistence fails.
        """

        model = self._get_attempt_model(attempt_id)
        updated = self._to_generation_attempt(model).start(at=at)
        return self._persist_attempt_update(model, updated)

    def checkpoint_generation_attempt(
        self, attempt_id: UUID, partial_content: str
    ) -> GenerationAttemptRecord:
        """Replace partial content for a streaming attempt.

        Args:
            attempt_id:
                Identifier of the streaming attempt.
            partial_content:
                Complete output accumulated so far.

        Returns:
            The persisted streaming attempt.

        Raises:
            LookupError:
                If the attempt does not exist.
            InvalidGenerationAttemptTransitionError:
                If the attempt is not streaming.
            SQLAlchemyError:
                If persistence fails.
        """

        model = self._get_attempt_model(attempt_id)
        updated = self._to_generation_attempt(model).checkpoint(partial_content)
        return self._persist_attempt_update(model, updated)

    def complete_generation_attempt(
        self, attempt_id: UUID, assistant_content: str, *, at: datetime
    ) -> GenerationAttemptRecord:
        """Atomically persist an assistant message and complete its attempt.

        Args:
            attempt_id:
                Identifier of the streaming attempt.
            assistant_content:
                Completed assistant response.
            at:
                Time generation completed.

        Returns:
            The completed attempt linked to the new assistant message.

        Raises:
            LookupError:
                If the attempt does not exist.
            InvalidGenerationAttemptTransitionError:
                If the attempt is not streaming or the timestamp is invalid.
            SQLAlchemyError:
                If persistence fails.
        """

        model = self._get_attempt_model(attempt_id)
        message_id = uuid4()
        updated = self._to_generation_attempt(model).complete(
            assistant_message_id=message_id,
            at=at,
        )
        message = Message(
            id=message_id,
            conversation_id=updated.conversation_id,
            role=ChatRole.ASSISTANT,
            content=assistant_content,
            created_at=at,
        )
        self._apply_attempt(model, updated)

        try:
            self._session.add(message)
            self._session.commit()
            return updated

        except SQLAlchemyError:
            self._session.rollback()

            logger.exception("Failed to complete generation attempt %s.", attempt_id)
            raise

    def fail_generation_attempt(
        self,
        attempt_id: UUID,
        *,
        error_code: str,
        at: datetime,
        error_detail: str | None = None,
        partial_content: str | None = None,
    ) -> GenerationAttemptRecord:
        """Persist a failed terminal state with normalized safe diagnostics.

        Args:
            attempt_id:
                Identifier of the streaming attempt.
            error_code:
                Stable normalized failure code.
            at:
                Time generation failed.
            error_detail:
                Optional safe user-facing detail.
            partial_content:
                Optional complete partial output.

        Returns:
            The persisted failed attempt.

        Raises:
            LookupError:
                If the attempt does not exist.
            InvalidGenerationAttemptTransitionError:
                If the attempt is not streaming or failure data is invalid.
            SQLAlchemyError:
                If persistence fails.
        """

        model = self._get_attempt_model(attempt_id)
        updated = self._to_generation_attempt(model).fail(
            error_code=error_code,
            error_detail=error_detail,
            partial_content=partial_content,
            at=at,
        )
        return self._persist_attempt_update(model, updated)

    def interrupt_generation_attempt(
        self,
        attempt_id: UUID,
        *,
        at: datetime,
        partial_content: str | None = None,
    ) -> GenerationAttemptRecord:
        """Persist an interrupted terminal state.

        Args:
            attempt_id:
                Identifier of the streaming attempt.
            at:
                Time generation was interrupted.
            partial_content:
                Optional complete partial output.

        Returns:
            The persisted interrupted attempt.

        Raises:
            LookupError:
                If the attempt does not exist.
            InvalidGenerationAttemptTransitionError:
                If the attempt is not streaming or the timestamp is invalid.
            SQLAlchemyError:
                If persistence fails.
        """

        model = self._get_attempt_model(attempt_id)
        updated = self._to_generation_attempt(model).interrupt(
            partial_content=partial_content,
            at=at,
        )
        return self._persist_attempt_update(model, updated)

    def get_generation_attempt(
        self, attempt_id: UUID
    ) -> GenerationAttemptRecord | None:
        """Retrieve an attempt by identifier.

        Args:
            attempt_id:
                Identifier of the attempt to retrieve.

        Returns:
            The matching attempt, or ``None`` when it does not exist.
        """

        model = self._session.get(GenerationAttempt, attempt_id)
        return self._to_generation_attempt(model) if model is not None else None

    def get_unresolved_generation_attempts(
        self, conversation_id: UUID
    ) -> list[GenerationAttemptRecord]:
        """Retrieve pending and streaming attempts for a conversation.

        Args:
            conversation_id:
                Identifier of the conversation to inspect.

        Returns:
            Unresolved attempts ordered from oldest to newest.
        """

        statement = (
            select(GenerationAttempt)
            .where(
                GenerationAttempt.conversation_id == conversation_id,
                GenerationAttempt.status.in_(
                    (
                        GenerationAttemptStatus.PENDING,
                        GenerationAttemptStatus.STREAMING,
                    )
                ),
            )
            .order_by(GenerationAttempt.created_at.asc())
        )
        return [
            self._to_generation_attempt(model)
            for model in self._session.scalars(statement)
        ]

    @staticmethod
    def _to_conversation_record(conversation: Conversation) -> ConversationRecord:
        """Translate a persistence model into a domain record.

        Args:
            conversation:
                Persistence model to translate.

        Returns:
            Persistence-neutral conversation record.
        """

        return ConversationRecord(
            id=conversation.id,
            title=conversation.title,
            provider_id=(
                ProviderId(conversation.provider_id)
                if conversation.provider_id is not None
                else None
            ),
            model_id=(
                ModelId(conversation.model_id)
                if conversation.model_id is not None
                else None
            ),
            requested_generation_configuration=(
                ConversationRepository._configuration_from_dict(
                    conversation.requested_generation_configuration
                )
            ),
        )

    @staticmethod
    def _to_message_record(message: Message) -> MessageRecord:
        """Translate a persistence model into a domain record."""

        return MessageRecord(
            id=message.id,
            conversation_id=message.conversation_id,
            role=message.role,
            content=message.content,
        )

    def _get_attempt_model(self, attempt_id: UUID) -> GenerationAttempt:
        """Load and lock an attempt for a lifecycle transition.

        Args:
            attempt_id:
                Identifier of the attempt to load.

        Returns:
            The locked persistence model.

        Raises:
            LookupError:
                If no matching attempt exists.
        """

        statement = (
            select(GenerationAttempt)
            .where(GenerationAttempt.id == attempt_id)
            .with_for_update()
        )
        model = self._session.scalar(statement)
        if model is None:
            raise LookupError(f"Generation attempt {attempt_id} does not exist.")
        return model

    def _persist_attempt_update(
        self,
        model: GenerationAttempt,
        attempt: GenerationAttemptRecord,
    ) -> GenerationAttemptRecord:
        """Apply and commit a validated attempt snapshot.

        Args:
            model:
                Persistence model to update.
            attempt:
                Validated domain snapshot to persist.

        Returns:
            The persisted domain snapshot.

        Raises:
            SQLAlchemyError:
                If persistence fails.
        """

        self._apply_attempt(model, attempt)
        try:
            self._session.commit()
            return attempt

        except SQLAlchemyError:
            self._session.rollback()

            logger.exception("Failed to update generation attempt %s.", attempt.id)
            raise

    @staticmethod
    def _apply_attempt(
        model: GenerationAttempt,
        attempt: GenerationAttemptRecord,
    ) -> None:
        """Copy mutable lifecycle fields from a validated domain snapshot.

        Args:
            model:
                Persistence model to update.
            attempt:
                Validated domain snapshot.
        """

        model.status = attempt.status
        model.started_at = attempt.started_at
        model.finished_at = attempt.finished_at
        model.partial_content = attempt.partial_content
        model.error_code = attempt.error_code
        model.error_detail = attempt.error_detail
        model.assistant_message_id = attempt.assistant_message_id

    @staticmethod
    def _from_generation_attempt(
        attempt: GenerationAttemptRecord,
    ) -> GenerationAttempt:
        """Translate a domain attempt into a persistence model.

        Args:
            attempt:
                Domain attempt to translate.

        Returns:
            New persistence model.
        """

        return GenerationAttempt(
            id=attempt.id,
            conversation_id=attempt.conversation_id,
            source_user_message_id=attempt.source_user_message_id,
            provider_id=str(attempt.provider_id),
            model_id=str(attempt.model_id),
            effective_configuration=ConversationRepository._configuration_to_dict(
                attempt.effective_configuration
            ),
            status=attempt.status,
            partial_content=attempt.partial_content,
            error_code=attempt.error_code,
            error_detail=attempt.error_detail,
            assistant_message_id=attempt.assistant_message_id,
            created_at=attempt.created_at,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
        )

    @staticmethod
    def _to_generation_attempt(
        model: GenerationAttempt,
    ) -> GenerationAttemptRecord:
        """Translate a persistence model into an immutable domain attempt.

        Args:
            model:
                Persistence model to translate.

        Returns:
            Immutable domain snapshot.

        Raises:
            ValueError:
                If persisted configuration, timestamps, or lifecycle fields are
                invalid.
        """

        created_at = ConversationRepository._timezone_aware(model.created_at)
        if created_at is None:
            raise ValueError("Persisted generation attempt has no creation time.")

        return GenerationAttemptRecord(
            id=model.id,
            conversation_id=model.conversation_id,
            source_user_message_id=model.source_user_message_id,
            provider_id=ProviderId(model.provider_id),
            model_id=ModelId(model.model_id),
            effective_configuration=ConversationRepository._configuration_from_dict(
                model.effective_configuration
            ),
            status=model.status,
            partial_content=model.partial_content,
            error_code=model.error_code,
            error_detail=model.error_detail,
            assistant_message_id=model.assistant_message_id,
            created_at=created_at,
            started_at=ConversationRepository._timezone_aware(model.started_at),
            finished_at=ConversationRepository._timezone_aware(model.finished_at),
        )

    @staticmethod
    def _configuration_to_dict(
        configuration: GenerationConfiguration,
    ) -> dict[str, Any]:
        """Serialize provider-neutral generation configuration.

        Args:
            configuration:
                Configuration value to serialize.

        Returns:
            JSON-compatible configuration mapping.
        """

        return {
            "temperature": configuration.temperature,
            "top_p": configuration.top_p,
            "max_output_tokens": configuration.max_output_tokens,
            "seed": configuration.seed,
        }

    @staticmethod
    def _configuration_from_dict(
        values: dict[str, Any],
    ) -> GenerationConfiguration:
        """Deserialize provider-neutral generation configuration.

        Args:
            values:
                JSON-compatible configuration mapping.

        Returns:
            Validated configuration value.

        Raises:
            InvalidGenerationConfigurationError:
                If a persisted generation setting is invalid.
        """

        return GenerationConfiguration(
            temperature=values.get("temperature"),
            top_p=values.get("top_p"),
            max_output_tokens=values.get("max_output_tokens"),
            seed=values.get("seed"),
        )

    @staticmethod
    def _timezone_aware(value: datetime | None) -> datetime | None:
        """Normalize SQLite-naive timestamps to UTC for domain invariants.

        Args:
            value:
                Persisted timestamp.

        Returns:
            The timestamp with timezone information, when present.
        """

        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)

    def delete_conversation(
        self,
        conversation_id: UUID,
    ) -> bool:
        """
        Delete a conversation and all associated messages.

        Args:
            conversation_id:
                Unique conversation identifier.

        Returns:
            True if the conversation was found and deleted,
            otherwise False.

        Raises:
            SQLAlchemyError:
                If deletion fails.
        """

        try:
            conversation = self._session.get(
                Conversation,
                conversation_id,
            )
            if conversation is None:
                logger.warning(
                    "Conversation %s not found for deletion.",
                    conversation_id,
                )
                return False

            self._session.delete(conversation)
            self._session.commit()

            logger.info(
                "Deleted conversation %s",
                conversation_id,
            )
            return True

        except SQLAlchemyError:
            self._session.rollback()

            logger.exception(
                "Failed to delete conversation %s",
                conversation_id,
            )
            raise
