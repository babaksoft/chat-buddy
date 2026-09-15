"""Compatibility exports for Chat database session wiring."""

from chat_buddy.chat.infrastructure.db.session import (
    ChatSessionLocal,
    chat_engine,
)

SessionLocal = ChatSessionLocal
engine = chat_engine

__all__ = ["SessionLocal", "engine"]
