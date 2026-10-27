"""Lazy composition of the Characters durable Ongoing backend."""

from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import (
    BaselineMemoryContextSelector,
    BaselineResponseMemorySelector,
    ConversationService,
    StorylineConversationAdapter,
    StorylineExtractionContextService,
    StorylineMemoryEligibility,
    StorylineMemoryExtractionService,
    StorylineResponseMemoryService,
)
from chat_buddy.characters.domain import ExtractionBudget, ResponseMemoryBudget
from chat_buddy.characters.infrastructure.llm import (
    ContextualMemoryDeltaExtractor,
    create_model_registry,
)

_EXTRACTION_FIXED_OVERHEAD_TOKENS = 512
_RESPONSE_MEMORY_BUDGET_TOKENS = 1024


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

    from chat_buddy.characters.infrastructure.db import CharactersSessionLocal
    from chat_buddy.characters.infrastructure.db.repositories import (
        DbContinuityRepository,
        DbConversationRepository,
        DbIdentityRepository,
        DbMemoryExtractionRepository,
        DbPersonaRepository,
        DbSceneRepository,
        DbStorylineMemoryRepository,
        DbStorylineRepository,
        DbSummaryRepository,
    )

    if session_factory is None:
        session_factory = CharactersSessionLocal

    storylines = DbStorylineRepository(session_factory)
    scenes = DbSceneRepository(session_factory)
    conversations = DbConversationRepository(session_factory)
    identities = DbIdentityRepository(session_factory)
    personas = DbPersonaRepository(session_factory)
    summaries = DbSummaryRepository(session_factory)
    memories = DbStorylineMemoryRepository(session_factory)
    effects = DbMemoryExtractionRepository(session_factory)
    models = create_model_registry()
    response_memories = StorylineResponseMemoryService(
        scenes,
        conversations,
        memories,
        BaselineResponseMemorySelector(),
        ResponseMemoryBudget(input_tokens=_RESPONSE_MEMORY_BUDGET_TOKENS),
    )
    extraction = None
    if any("memory_extraction" in model.capabilities for model in models.list_models()):
        extraction_generation = models.resolve_default("memory_extraction")
        extraction_contexts = StorylineExtractionContextService(
            identities,
            personas,
            storylines,
            scenes,
            conversations,
            summaries,
            memories,
            StorylineMemoryEligibility(),
            BaselineMemoryContextSelector(
                models.token_counter(extraction_generation.model.provider)
            ),
        )
        extraction = StorylineMemoryExtractionService(
            extraction_contexts,
            ContextualMemoryDeltaExtractor(
                models.memory_extraction_gateway(extraction_generation.model.provider),
                extraction_generation,
            ),
            memories,
            effects,
            ExtractionBudget(
                input_tokens=extraction_generation.input_tokens,
                fixed_overhead_tokens=min(
                    _EXTRACTION_FIXED_OVERHEAD_TOKENS,
                    extraction_generation.input_tokens - 1,
                ),
            ),
        )
    return ConversationService(
        conversations,
        DbContinuityRepository(session_factory),
        identities,
        personas,
        summaries,
        models,
        storyline_adapter=StorylineConversationAdapter(storylines, scenes),
        memory_extraction=extraction,
        response_memories=response_memories,
    )
