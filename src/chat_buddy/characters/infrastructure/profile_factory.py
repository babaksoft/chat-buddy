"""Lazy composition of Characters profile and lifecycle services."""

from chat_buddy.characters.application import (
    ContinuityService,
    IdentityService,
    PersonaService,
    StorylineForkService,
    StorylineMemoryService,
    StorylineService,
)


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


def create_storyline_memory_service() -> StorylineMemoryService:
    """Build continuity-scoped Storyline memory management operations.

    Returns:
        Lazily configured Storyline memory application operations.
    """

    from chat_buddy.characters.infrastructure.db import CharactersSessionLocal
    from chat_buddy.characters.infrastructure.db.repositories import (
        DbMemoryExtractionRepository,
        DbStorylineMemoryRepository,
    )

    return StorylineMemoryService(
        DbStorylineMemoryRepository(CharactersSessionLocal),
        DbMemoryExtractionRepository(CharactersSessionLocal),
    )
