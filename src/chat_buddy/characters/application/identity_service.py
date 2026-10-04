"""Identity management operations independent of UI and database libraries."""

from uuid import UUID

from chat_buddy.characters.domain import (
    FrozenIdentityError,
    Identity,
    IdentityDetails,
    IdentityRepository,
    StaleIdentityError,
)


class IdentityService:
    """Manage editable identities and independent duplicates."""

    def __init__(self, repository: IdentityRepository) -> None:
        """Initialize the identity service.

        Args:
            repository:
                Repository responsible for atomic identity persistence.
        """

        self._repository = repository

    def create(self, details: IdentityDetails) -> Identity:
        """Create an editable identity.

        Args:
            details:
                Validated authored fields.

        Returns:
            The persisted identity.
        """

        return self._repository.create(details)

    def ensure_default(self) -> Identity:
        """Idempotently setup the one and only You identity.

        Returns:
            The sole default identity.
        """

        return self._repository.ensure_default()

    def inspect(self, identity_id: UUID) -> Identity:
        """Inspect a persisted identity.

        Args:
            identity_id:
                Stable identity identifier.

        Returns:
            The current identity snapshot.

        Raises:
            IdentityNotFoundError:
                If the requested identity does not exist.
        """

        return self._repository.get(identity_id)

    def list(self) -> list[Identity]:
        """List persisted identities in deterministic order.

        Returns:
            Default-first identity snapshots.
        """

        return self._repository.list()

    def edit(
        self, identity_id: UUID, details: IdentityDetails, expected_revision: int
    ) -> Identity:
        """Replace authored fields before first use, rejecting stale edits.

        Args:
            identity_id:
                Stable identity identifier.
            details:
                Validated replacement fields.
            expected_revision:
                Revision shown to the caller before editing.

        Returns:
            The new immutable snapshot with the same identifier.

        Raises:
            IdentityNotFoundError:
                If the requested identity does not exist.
            FrozenIdentityError:
                If first use has frozen the identity.
            StaleIdentityError:
                If the caller's revision is outdated.
        """

        current = self.inspect(identity_id)
        if current.is_frozen:
            raise FrozenIdentityError("Duplicate this frozen identity to edit it")
        if current.revision != expected_revision:
            raise StaleIdentityError("Reload the identity before editing")

        return self._repository.replace(identity_id, details, expected_revision)

    def duplicate(
        self, identity_id: UUID, details: IdentityDetails | None = None
    ) -> Identity:
        """Create a fresh editable identity containing only authored fields.

        Args:
            identity_id:
                Identifier of the source, which remains unchanged.
            details:
                Optional validated revisions to the copied fields.

        Returns:
            A new non-default identity without frozen status or history.

        Raises:
            IdentityNotFoundError:
                If the source identity does not exist.
        """

        source = self.inspect(identity_id)
        return self._repository.create(
            details if details is not None else source.details
        )
