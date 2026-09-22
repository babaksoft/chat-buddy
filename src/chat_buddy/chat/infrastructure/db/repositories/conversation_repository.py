import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from chat_buddy.chat.domain import (
    ChatRole,
    ConversationRecord,
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
    """Provide persistence for conversations and standalone messages."""

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

    def get_unmatched_user_message(self, conversation_id: UUID) -> MessageRecord | None:
        """Return the unanswered final user message, when present.

        Args:
            conversation_id:
                Conversation whose linear tail should be inspected.

        Returns:
            Unmatched user-message tail, or ``None`` when the final turn closed.
        """

        statement = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
        message = self._session.scalar(statement)
        if message is None or message.role is not ChatRole.USER:
            return None
        return self._to_message_record(message)

    def edit_unmatched_user_message(
        self, conversation_id: UUID, content: str
    ) -> MessageRecord:
        """Edit the unmatched final user message while no attempt is open.

        Args:
            conversation_id:
                Conversation containing the editable tail.
            content:
                Replacement nonblank user content.

        Returns:
            Updated unmatched user message.

        Raises:
            LookupError:
                If no unmatched user-message tail exists.
            InvalidGenerationAttemptTransitionError:
                If a generation attempt is open.
            ValueError:
                If replacement content is blank.
        """

        if not content.strip():
            raise ValueError("User message content must be non-empty.")
        if self._has_open_generation_attempt(conversation_id):
            raise InvalidGenerationAttemptTransitionError(
                "Cannot edit an unmatched user message while an attempt is open."
            )
        tail = self.get_unmatched_user_message(conversation_id)
        if tail is None:
            raise LookupError(
                f"Conversation {conversation_id} has no unmatched user message."
            )

        model = self._session.get(Message, tail.id)
        if model is None:
            raise LookupError(f"Message {tail.id} does not exist.")

        model.content = content
        try:
            self._session.commit()
        except SQLAlchemyError:
            self._session.rollback()
            logger.exception("Failed to edit unmatched message %s.", tail.id)
            raise

        return self._to_message_record(model)

    def _has_open_generation_attempt(self, conversation_id: UUID) -> bool:
        """Return whether a generation attempt currently owns the message tail.

        Args:
            conversation_id:
                Conversation whose message tail is being edited.

        Returns:
            Whether a pending or streaming attempt exists.
        """

        statement = (
            select(GenerationAttempt.id)
            .where(
                GenerationAttempt.conversation_id == conversation_id,
                GenerationAttempt.status.in_(
                    (
                        GenerationAttemptStatus.PENDING,
                        GenerationAttemptStatus.STREAMING,
                    )
                ),
            )
            .limit(1)
        )
        return self._session.scalar(statement) is not None

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
