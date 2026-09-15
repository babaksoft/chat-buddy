from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

CHAT_SCHEMA = "chat"


class ChatBase(DeclarativeBase):
    """Declarative base for Chat persistence models."""

    metadata = MetaData(schema=CHAT_SCHEMA)
