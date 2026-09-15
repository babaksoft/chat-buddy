from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from chat_buddy.chat.infrastructure.config import settings

chat_engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
)

ChatSessionLocal = sessionmaker(
    bind=chat_engine,
    autoflush=False,
)
