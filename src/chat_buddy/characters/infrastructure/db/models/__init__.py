"""Registry of SQLAlchemy persistence models."""

from chat_buddy.characters.infrastructure.db.models.continuity import (
    ContinuityModel,
    ConversationModel,
    SceneModel,
    StartingRelationshipModel,
    StorylineModel,
)
from chat_buddy.characters.infrastructure.db.models.evolution import (
    EvolutionEffectModel,
    EvolutionEventModel,
    PersonaAdaptationProjectionModel,
    RelationshipProjectionModel,
)
from chat_buddy.characters.infrastructure.db.models.identity import IdentityModel
from chat_buddy.characters.infrastructure.db.models.memory import (
    MemoryConflictModel,
    MemoryEvidenceModel,
    MemoryExtractionEffectModel,
    MemoryRevisionModel,
    StorylineMemoryModel,
)
from chat_buddy.characters.infrastructure.db.models.message import (
    GenerationAttemptModel,
    MessageModel,
)
from chat_buddy.characters.infrastructure.db.models.persona import PersonaModel
from chat_buddy.characters.infrastructure.db.models.summary import SummaryRevisionModel

__all__ = [
    "ContinuityModel",
    "ConversationModel",
    "EvolutionEffectModel",
    "EvolutionEventModel",
    "GenerationAttemptModel",
    "IdentityModel",
    "MemoryConflictModel",
    "MemoryEvidenceModel",
    "MemoryExtractionEffectModel",
    "MemoryRevisionModel",
    "MessageModel",
    "PersonaAdaptationProjectionModel",
    "PersonaModel",
    "RelationshipProjectionModel",
    "SceneModel",
    "StartingRelationshipModel",
    "StorylineMemoryModel",
    "StorylineModel",
    "SummaryRevisionModel",
]
