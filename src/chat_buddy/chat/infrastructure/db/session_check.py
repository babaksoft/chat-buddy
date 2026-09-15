from sqlalchemy import text

from chat_buddy.chat.infrastructure.db.session import ChatSessionLocal

with ChatSessionLocal() as session:
    result = session.execute(text("SELECT 1"))

    print(result.scalar())
