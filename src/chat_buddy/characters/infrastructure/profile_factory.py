"""Lazy composition of Characters profile and lifecycle services."""

from chat_buddy.characters.application import (
    ContinuityService,
    IdentityService,
    PersonaService,
)


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
        DbIdentityRepository,
        DbPersonaRepository,
    )

    return (
        IdentityService(DbIdentityRepository(CharactersSessionLocal)),
        PersonaService(DbPersonaRepository(CharactersSessionLocal)),
        ContinuityService(DbContinuityRepository(CharactersSessionLocal)),
    )
