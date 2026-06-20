"""
Repository layer for chat_buddy database operations.

This module provides high-level CRUD operations for conversations and messages.
It abstracts SQLAlchemy session usage and keeps database logic separate from
business logic and UI layers.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from .models import Conversation, Message


class ConversationRepository:
    """Repository for managing Conversation entities.

    This class encapsulates all database operations related to conversations,
    including creation, retrieval, listing, and summary updates.
    """

    def __init__(self, session: Session):
        """Initialize the repository.

        Args:
            session (Session): SQLAlchemy session used for database operations.
        """
        self.session = session

    def create_conversation(self, title: str) -> Conversation:
        """Create a new conversation.

        Args:
            title (str): Title for the conversation.

        Returns:
            Conversation: The newly created conversation instance.
        """
        conv = Conversation(title=title)
        self.session.add(conv)
        self.session.commit()
        self.session.refresh(conv)
        return conv

    def get_conversation(self, conversation_id: UUID) -> Optional[Conversation]:
        """Retrieve a conversation by its ID.

        Args:
            conversation_id (UUID): Unique identifier of the conversation.

        Returns:
            Optional[Conversation]: The conversation if found, otherwise None.
        """
        return (
            self.session.query(Conversation)
            .filter(Conversation.id == conversation_id)
            .first()
        )

    def list_conversations(self) -> List[Conversation]:
        """List all conversations ordered by most recent update.

        Returns:
            List[Conversation]: All conversations sorted by `updated_at` descending.
        """
        return (
            self.session.query(Conversation)
            .order_by(Conversation.updated_at.desc())
            .all()
        )

    def update_summary(self, conversation_id: UUID, summary: str) -> None:
        """Update the running summary of a conversation.

        Args:
            conversation_id (UUID): ID of the conversation to update.
            summary (str): New summary text.

        Returns:
            None
        """
        conv = self.get_conversation(conversation_id)
        if conv:
            conv.summary = summary
            conv.updated_at = datetime.utcnow()
            self.session.commit()


class MessageRepository:
    """Repository for managing Message entities.

    This class provides operations for adding and retrieving messages
    associated with a conversation.
    """

    def __init__(self, session: Session):
        """Initialize the repository.

        Args:
            session (Session): SQLAlchemy session used for database operations.
        """
        self.session = session

    def add_message(
        self,
        conversation_id: UUID,
        role: str,
        content: str,
    ) -> Message:
        """Add a new message to a conversation.

        Args:
            conversation_id (UUID): ID of the parent conversation.
            role (str): Role of the sender ('user', 'assistant', etc.).
            content (str): Message text.

        Returns:
            Message: The newly created message instance.
        """
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
        )
        self.session.add(msg)

        # Update conversation timestamp
        conv = (
            self.session.query(Conversation)
            .filter(Conversation.id == conversation_id)
            .first()
        )
        if conv:
            conv.updated_at = datetime.utcnow()

        self.session.commit()
        self.session.refresh(msg)
        return msg

    def get_messages(self, conversation_id: UUID) -> List[Message]:
        """Retrieve all messages for a conversation.

        Args:
            conversation_id (UUID): ID of the conversation.

        Returns:
            List[Message]: Messages ordered by creation time ascending.
        """
        return (
            self.session.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .all()
        )
