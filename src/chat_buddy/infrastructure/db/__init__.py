"""Compatibility exports for the relocated Chat persistence layer."""

from chat_buddy.chat.infrastructure.db import (
    ChatBase,
    ChatSessionLocal,
    chat_engine,
)

Base = ChatBase
SessionLocal = ChatSessionLocal
engine = chat_engine

__all__ = [
    "Base",
    "SessionLocal",
    "engine",
]
