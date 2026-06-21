from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from chat_buddy.infrastructure.config.settings import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    echo=False,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)
