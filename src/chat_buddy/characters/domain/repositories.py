"""Characters-owned persistence contracts."""

from typing import Protocol
from uuid import UUID

from chat_buddy.characters.domain.continuity import (
    Continuity,
    StartContinuity,
    StartingRelationship,
)
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


class ContinuityRepository(Protocol):
    """Persist lifecycle and ownership without exposing database objects."""

    def start(
        self, request: StartContinuity, relationship: StartingRelationship
    ) -> Continuity:
        """Atomically verify, freeze, and persist an idempotent confirmed start.

        Args:
            request:
                Complete reviewed confirmation.
            relationship:
                Resolved starting state and provenance.

        Returns:
            New continuity or the original identical confirmation result.
        """

        ...

    def find_confirmation(self, request: StartContinuity) -> Continuity | None:
        """Read an identical persisted confirmation before preflight checks.

        Args:
            request:
                Complete confirmed request.

        Returns:
            Original continuity, or None for a new confirmation.

        Raises:
            ConfirmationConflictError:
                If submitted data differs from the persisted confirmation.
        """

        ...

    def find_active(self, identity_id: UUID, persona_id: UUID) -> Continuity | None:
        """Find the pair's active Ongoing for application preflight checks.

        Args:
            identity_id:
                Selected identity owner.
            persona_id:
                Selected persona owner.

        Returns:
            Active Ongoing snapshot, or None if the pair has no active Ongoing.
        """

        ...

    def get(
        self, identity_id: UUID, persona_id: UUID, continuity_id: UUID
    ) -> Continuity:
        """Read within explicit identity/persona ownership, including archives.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            continuity_id:
                Continuity to inspect.

        Returns:
            The owned continuity snapshot.
        """

        ...

    def list(self) -> list[Continuity]:
        """Read snapshots ordered by identity, persona, and continuity UUID.

        Returns:
            All independently owned lifecycle snapshots.
        """

        ...

    def archive(
        self, identity_id: UUID, persona_id: UUID, continuity_id: UUID
    ) -> Continuity:
        """Lock and permanently archive a continuity within its ownership scope.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            continuity_id:
                Continuity to archive.

        Returns:
            The archived snapshot, including repeated archive requests.
        """

        ...
