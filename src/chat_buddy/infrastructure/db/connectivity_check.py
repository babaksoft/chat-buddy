from sqlalchemy import text

from chat_buddy.infrastructure.db.session import SessionLocal

with SessionLocal() as session:
    result = session.execute(text("SELECT 1"))

    print(result.scalar())
