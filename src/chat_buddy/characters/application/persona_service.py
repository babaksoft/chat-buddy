"""Persona management operations independent of UI and database libraries."""

from uuid import UUID

from chat_buddy.characters.domain.errors import FrozenPersonaError, StalePersonaError
from chat_buddy.characters.domain.persona import Persona, PersonaCore
from chat_buddy.characters.domain.repositories import PersonaRepository


class PersonaService:
    """Manage editable personas and independent duplicates."""

    def __init__(self, repository: PersonaRepository) -> None:
        """Bind the Characters persistence contract.

        Args:
            repository:
                Repository responsible for atomic persona persistence.
        """

        self._repository = repository

    def create(self, core: PersonaCore) -> Persona:
        """Create an editable persona with validated authored content.

        Args:
            core:
                Validated authored fields.

        Returns:
            The persisted persona.
        """

        return self._repository.create(core)

    def inspect(self, persona_id: UUID) -> Persona:
        """Inspect a persisted persona.

        Args:
            persona_id:
                Stable persona identifier.

        Returns:
            The current persona snapshot.

        Raises:
            PersonaNotFoundError:
                If the requested persona does not exist.
        """

        return self._repository.get(persona_id)

    def list(self) -> list[Persona]:
        """List persisted personas in deterministic order.

        Returns:
            Persona snapshots ordered by name and identifier.
        """

        return self._repository.list()

    def edit(
        self, persona_id: UUID, core: PersonaCore, expected_revision: int
    ) -> Persona:
        """Replace authored fields before first use, rejecting stale edits.

        Args:
            persona_id:
                Stable persona identifier.
            core:
                Validated replacement fields.
            expected_revision:
                Revision shown to the caller before editing.

        Returns:
            The new immutable snapshot with the same identifier.

        Raises:
            PersonaNotFoundError:
                If the requested persona does not exist.
            FrozenPersonaError:
                If first use has frozen the persona.
            StalePersonaError:
                If the caller's revision is outdated.
        """

        current = self.inspect(persona_id)
        if current.is_frozen:
            raise FrozenPersonaError("Duplicate this frozen persona to edit it")
        if current.revision != expected_revision:
            raise StalePersonaError("Reload the persona before editing")

        return self._repository.replace(persona_id, core, expected_revision)

    def duplicate(self, persona_id: UUID, core: PersonaCore | None = None) -> Persona:
        """Create a fresh editable persona containing only authored fields.

        Args:
            persona_id:
                Identifier of the source, which remains unchanged.
            core:
                Optional validated revisions to the copied fields.

        Returns:
            A new editable persona without frozen status or history.

        Raises:
            PersonaNotFoundError:
                If the source persona does not exist.
        """

        source = self.inspect(persona_id)
        return self._repository.create(core if core is not None else source.core)
