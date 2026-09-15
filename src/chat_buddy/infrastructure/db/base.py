"""Compatibility exports for the Chat declarative base."""

from chat_buddy.chat.infrastructure.db.base import ChatBase

Base = ChatBase

__all__ = ["Base"]
