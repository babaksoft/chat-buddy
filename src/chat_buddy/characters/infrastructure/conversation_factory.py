"""Lazy composition of the Characters durable Ongoing backend."""

from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import ConversationService
from chat_buddy.characters.infrastructure.db import (
    CharactersSessionLocal,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbConversationRepository,
    DbIdentityRepository,
    DbPersonaRepository,
    DbSummaryRepository,
)
from chat_buddy.characters.infrastructure.llm import (
    create_model_registry,
)


def create_conversation_service(
    session_factory: sessionmaker[Session] | None = None,
) -> ConversationService:
    """Compose repositories and configured local providers only on explicit use.

    Args:
        session_factory:
            Optional isolated Characters sessions; otherwise use area settings.

    Returns:
        Ready Ongoing application service without initializing Chat.
    """

    if session_factory is None:
        session_factory = CharactersSessionLocal

    return ConversationService(
        DbConversationRepository(session_factory),
        DbContinuityRepository(session_factory),
        DbIdentityRepository(session_factory),
        DbPersonaRepository(session_factory),
        DbSummaryRepository(session_factory),
        create_model_registry(),
    )
