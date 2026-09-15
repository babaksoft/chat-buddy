import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from chat_buddy.chat.domain import ChatRole, ConversationRecord, MessageRecord
from chat_buddy.chat.infrastructure.db.models import (
    Conversation,
    Message,
)

logger = logging.getLogger(__name__)


class ConversationRepository:
    """Provides persistence operations for conversations."""

    def __init__(self, session: Session) -> None:
        """
        Initialize the repository.

        Args:
            session: SQLAlchemy session.
        """

        self._session = session

    def create_conversation(
        self,
        title: str | None = None,
    ) -> ConversationRecord:
        """
        Create and persist a new conversation.

        Args:
            title:
                Optional conversation title.

        Returns:
            The newly created conversation.

        Raises:
            SQLAlchemyError:
                If conversation persistence fails.
        """

        try:
            conversation = Conversation(
                title=title,
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

    @staticmethod
    def _to_conversation_record(conversation: Conversation) -> ConversationRecord:
        """Translate a persistence model into a domain record."""

        return ConversationRecord(
            id=conversation.id,
            title=conversation.title,
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
