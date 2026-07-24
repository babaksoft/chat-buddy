"""
Application's persistence layer.
"""

from chat_buddy.infrastructure.db.base import Base
from chat_buddy.infrastructure.db.session import SessionLocal, engine

__all__ = [
    "Base",
    "engine",
    "SessionLocal",
]
