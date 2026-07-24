from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from chat_buddy.infrastructure.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
)
