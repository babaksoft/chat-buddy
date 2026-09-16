"""Engine and session factory for Characters persistence."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from chat_buddy.characters.infrastructure.config import settings

characters_engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
)

CharactersSessionLocal = sessionmaker(
    bind=characters_engine,
    autoflush=False,
)
