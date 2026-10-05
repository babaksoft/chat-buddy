"""Lazy composition of Characters profile and lifecycle services."""

from chat_buddy.characters.application import (
    ContinuityService,
    IdentityService,
    PersonaService,
)


def create_identity_service() -> IdentityService:
    """Build identity management without composing unrelated Characters services.

    Returns:
        Lazily configured identity application operations.
    """

    from chat_buddy.characters.infrastructure.db import CharactersSessionLocal
    from chat_buddy.characters.infrastructure.db.repositories import (
        DbIdentityRepository,
    )

    return IdentityService(DbIdentityRepository(CharactersSessionLocal))


def create_persona_service() -> PersonaService:
    """Build persona management without composing unrelated Characters services.

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
    """Build profile services only when the Characters page needs persistence.

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
