"""Characters-owned profile persistence contracts."""

from typing import Protocol
from uuid import UUID

from chat_buddy.characters.domain.identity import Identity, IdentityDetails
from chat_buddy.characters.domain.persona import Persona, PersonaCore


class IdentityRepository(Protocol):
    """Store identity snapshots without exposing persistence models."""

    def create(self, details: IdentityDetails) -> Identity:
        """Persist a new editable identity.

        Args:
            details:
                Authored fields to persist.

        Returns:
            The newly identified snapshot.
        """

        ...

    def ensure_default(self) -> Identity:
        """Return or atomically create the sole default You identity.

        Returns:
            The existing or newly created default identity.
        """

        ...

    def get(self, identity_id: UUID) -> Identity:
        """Read an identity or raise IdentityNotFoundError.

        Args:
            identity_id:
                Stable identity identifier.

        Returns:
            The persisted snapshot.

        Raises:
            IdentityNotFoundError:
                If the requested identity does not exist.
        """

        ...

    def list(self) -> list[Identity]:
        """Read identities ordered default-first, then name and identifier.

        Returns:
            Deterministically ordered snapshots.
        """

        ...

    def replace(
        self, identity_id: UUID, details: IdentityDetails, expected_revision: int
    ) -> Identity:
        """Atomically replace an editable identity at the expected revision.

        Args:
            identity_id:
                Stable identity identifier.
            details:
                Replacement authored fields.
            expected_revision:
                Last observed revision, rejecting stale writes.

        Returns:
            The updated snapshot.

        Raises:
            IdentityNotFoundError:
                If no such identity exists.
            FrozenIdentityError:
                If the persisted identity is frozen.
            StaleIdentityError:
                If a competing edit changed the revision.
        """

        ...


class PersonaRepository(Protocol):
    """Store persona snapshots without exposing persistence models."""

    def create(self, core: PersonaCore) -> Persona:
        """Persist a new editable persona.

        Args:
            core:
                Authored fields to persist.

        Returns:
            The newly identified snapshot.
        """

        ...

    def get(self, persona_id: UUID) -> Persona:
        """Read a persona or raise PersonaNotFoundError.

        Args:
            persona_id:
                Stable persona identifier.

        Returns:
            The persisted snapshot.

        Raises:
            PersonaNotFoundError:
                If the requested persona does not exist.
        """

        ...

    def list(self) -> list[Persona]:
        """Read personas ordered by name and identifier.

        Returns:
            Deterministically ordered snapshots.
        """

        ...

    def replace(
        self, persona_id: UUID, core: PersonaCore, expected_revision: int
    ) -> Persona:
        """Atomically replace an editable persona at the expected revision.

        Args:
            persona_id:
                Stable persona identifier.
            core:
                Replacement authored fields.
            expected_revision:
                Last observed revision, rejecting stale writes.

        Returns:
            The updated snapshot.

        Raises:
            PersonaNotFoundError:
                If no such persona exists.
            FrozenPersonaError:
                If the persisted persona is frozen.
            StalePersonaError:
                If a competing edit changed the revision.
        """

        ...
