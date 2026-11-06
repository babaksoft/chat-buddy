"""Lazy composition of Characters profile and lifecycle services."""

from chat_buddy.characters.application import (
    ContinuityMemoryService,
    ContinuityService,
    EvolutionEntryHistory,
    EvolutionInspectionService,
    EvolutionProjectionService,
    IdentityService,
    PersonaService,
    ResponseStyleService,
    StorylineForkService,
    StorylineService,
    TimelineService,
)


def create_response_style_service() -> ResponseStyleService:
    """Build shared continuity-scoped response-style operations.

    Returns:
        Lazily configured response-style application service.
    """

    from chat_buddy.characters.infrastructure.db import CharactersSessionLocal
    from chat_buddy.characters.infrastructure.db.repositories import (
        DbResponseStyleRepository,
    )

    return ResponseStyleService(DbResponseStyleRepository(CharactersSessionLocal))


def create_identity_service() -> IdentityService:
    """Build identity management service.

    Returns:
        Lazily configured identity application operations.
    """

    from chat_buddy.characters.infrastructure.db import CharactersSessionLocal
    from chat_buddy.characters.infrastructure.db.repositories import (
        DbIdentityRepository,
    )

    return IdentityService(DbIdentityRepository(CharactersSessionLocal))


def create_persona_service() -> PersonaService:
    """Build persona management service.

    Returns:
        Lazily configured persona application operations.
    """

    from chat_buddy.characters.infrastructure.db import CharactersSessionLocal
    from chat_buddy.characters.infrastructure.db.repositories import (
        DbPersonaRepository,
    )

    return PersonaService(DbPersonaRepository(CharactersSessionLocal))


def create_profile_services() -> (
    tuple[IdentityService, PersonaService, ContinuityService]
):
    """Build profile management services.

    Returns:
        Independently configured identity, persona, and continuity services.
    """

    from chat_buddy.characters.infrastructure.db import CharactersSessionLocal
    from chat_buddy.characters.infrastructure.db.repositories import (
        DbContinuityRepository,
    )

    return (
        create_identity_service(),
        create_persona_service(),
        ContinuityService(DbContinuityRepository(CharactersSessionLocal)),
    )


def create_ongoing_services() -> (
    tuple[IdentityService, PersonaService, ContinuityService]
):
    """Build the profile and lifecycle services used by Ongoing navigation.

    Returns:
        Identity, persona, and continuity application operations.
    """

    return create_profile_services()


def create_storyline_services() -> (
    tuple[IdentityService, PersonaService, StorylineService]
):
    """Build profile and lifecycle services used by Storyline pages.

    Returns:
        Identity, persona, and Storyline application operations.
    """

    from chat_buddy.characters.infrastructure.db import CharactersSessionLocal
    from chat_buddy.characters.infrastructure.db.repositories import (
        DbConversationRepository,
        DbSceneRepository,
        DbStorylineRepository,
    )

    return (
        create_identity_service(),
        create_persona_service(),
        StorylineService(
            DbStorylineRepository(CharactersSessionLocal),
            DbSceneRepository(CharactersSessionLocal),
            DbConversationRepository(CharactersSessionLocal),
        ),
    )


def create_timeline_services() -> (
    tuple[IdentityService, PersonaService, TimelineService]
):
    """Build profile and lifecycle services used by Timeline pages.

    Returns:
        Identity, persona, and Timeline application operations.
    """

    from chat_buddy.characters.infrastructure.clock import (
        SystemLocalTimezoneSource,
        SystemUtcClock,
    )
    from chat_buddy.characters.infrastructure.db import CharactersSessionLocal
    from chat_buddy.characters.infrastructure.db.repositories import (
        DbConversationRepository,
        DbTimelineDayRepository,
        DbTimelineRepository,
    )

    timelines = DbTimelineRepository(CharactersSessionLocal)
    days = DbTimelineDayRepository(CharactersSessionLocal)
    conversations = DbConversationRepository(CharactersSessionLocal)
    return (
        create_identity_service(),
        create_persona_service(),
        TimelineService(
            timelines,
            days,
            SystemLocalTimezoneSource(),
            graphs=conversations,
            clock=SystemUtcClock(),
        ),
    )


def create_storyline_fork_service() -> StorylineForkService:
    """Build reviewed structural Storyline fork operations.

    Returns:
        Lazily configured Storyline fork application operations.
    """

    from chat_buddy.characters.infrastructure.db import CharactersSessionLocal
    from chat_buddy.characters.infrastructure.db.repositories import (
        DbConversationRepository,
        DbIdentityRepository,
        DbPersonaRepository,
        DbSceneRepository,
        DbStorylineForkRepository,
        DbStorylineRepository,
    )

    conversations = DbConversationRepository(CharactersSessionLocal)
    return StorylineForkService(
        DbStorylineRepository(CharactersSessionLocal),
        DbSceneRepository(CharactersSessionLocal),
        conversations,
        conversations,
        DbIdentityRepository(CharactersSessionLocal),
        DbPersonaRepository(CharactersSessionLocal),
        DbStorylineForkRepository(CharactersSessionLocal),
    )


def create_continuity_memory_service() -> ContinuityMemoryService:
    """Build continuity-scoped memory management operations.

    Returns:
        Lazily configured shared memory application operations.
    """

    from chat_buddy.characters.infrastructure.db import CharactersSessionLocal
    from chat_buddy.characters.infrastructure.db.repositories import (
        DbContinuityMemoryRepository,
        DbMemoryExtractionRepository,
    )

    return ContinuityMemoryService(
        DbContinuityMemoryRepository(CharactersSessionLocal),
        DbMemoryExtractionRepository(CharactersSessionLocal),
    )


def create_evolution_inspection_service() -> EvolutionInspectionService:
    """Build shared evolution inspection and correction operations.

    Returns:
        Lazily configured continuity-scoped evolution operations.
    """

    from chat_buddy.characters.infrastructure.db import CharactersSessionLocal
    from chat_buddy.characters.infrastructure.db.repositories import (
        DbContinuityEntryRepository,
        DbContinuityRepository,
        DbConversationRepository,
        DbEvolutionRepository,
        DbStorylineRepository,
        DbTimelineDayRepository,
        DbTimelineRepository,
    )
    from chat_buddy.characters.infrastructure.evolution_observability import (
        default_evolution_observer,
    )

    evolution = DbEvolutionRepository(CharactersSessionLocal)
    conversations = DbConversationRepository(CharactersSessionLocal)
    projections = EvolutionProjectionService(
        evolution,
        DbContinuityRepository(CharactersSessionLocal),
        conversations,
        DbStorylineRepository(CharactersSessionLocal),
        default_evolution_observer(),
        timelines=DbTimelineRepository(CharactersSessionLocal),
        entry_history=EvolutionEntryHistory(
            DbContinuityEntryRepository(CharactersSessionLocal),
            conversations,
            DbTimelineDayRepository(CharactersSessionLocal),
        ),
    )
    return EvolutionInspectionService(evolution, conversations, projections)
