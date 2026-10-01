"""Registry of Characters-owned SQLAlchemy persistence models."""

from chat_buddy.characters.infrastructure.db.models.identity import IdentityModel
from chat_buddy.characters.infrastructure.db.models.persona import PersonaModel

__all__ = ["IdentityModel", "PersonaModel"]
