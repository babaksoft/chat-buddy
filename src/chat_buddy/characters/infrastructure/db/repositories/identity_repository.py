"""Transactional Characters identity repository."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    FrozenIdentityError,
    Identity,
    IdentityDetails,
    IdentityNotFoundError,
    StaleIdentityError,
)
from chat_buddy.characters.infrastructure.db.models import IdentityModel


class DbIdentityRepository:
    """Persist identity values in repository-owned transactions."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Initialize the identity repository.

        Args:
            session_factory:
                Factory used for creating database sessions.
        """

        self._session_factory = session_factory

    def create(self, details: IdentityDetails) -> Identity:
        """Persist a fresh editable identity.

        Args:
            details:
                Validated authored fields.

        Returns:
            The new persisted snapshot.
        """

        with self._session_factory() as session, session.begin():
            row = IdentityModel(**details.model_dump())
            session.add(row)
            session.flush()
            return self._snapshot(row)

    def ensure_default(self) -> Identity:
        """Use the database unique slot to resolve concurrent You setup.

        Returns:
            The existing or atomically created default snapshot.
        """

        with self._session_factory() as session, session.begin():
            query = select(IdentityModel).where(IdentityModel.default_key == "you")
            row = session.scalar(query)
            if row is None:
                try:
                    with session.begin_nested():
                        row = IdentityModel(name="You", default_key="you")
                        session.add(row)
                        session.flush()
                except IntegrityError:
                    row = session.scalar(query)
                    if row is None:
                        raise

            return self._snapshot(row)

    def get(self, identity_id: UUID) -> Identity:
        """Read a detached identity snapshot.

        Args:
            identity_id:
                Stable identity identifier.

        Returns:
            The current persisted snapshot.

        Raises:
            IdentityNotFoundError:
                If the identity does not exist.
        """

        with self._session_factory() as session:
            row = session.get(IdentityModel, identity_id)
            if row is None:
                raise IdentityNotFoundError(str(identity_id))

            return self._snapshot(row)

    def list(self) -> list[Identity]:
        """Read default-first identities, then name and UUID order.

        Returns:
            Deterministically ordered snapshots.
        """

        with self._session_factory() as session:
            rows = session.scalars(
                select(IdentityModel).order_by(
                    IdentityModel.default_key.is_(None),
                    IdentityModel.name,
                    IdentityModel.id,
                )
            )
            return [self._snapshot(row) for row in rows]

    def replace(
        self, identity_id: UUID, details: IdentityDetails, expected_revision: int
    ) -> Identity:
        """Replace fields using a revision/freeze conditional write.

        Args:
            identity_id:
                Stable identity identifier.
            details:
                Validated replacement fields.
            expected_revision:
                Last observed authored revision.

        Returns:
            The updated snapshot.

        Raises:
            IdentityNotFoundError:
                If the identity does not exist.
            FrozenIdentityError:
                If first use froze the identity before this write.
            StaleIdentityError:
                If another write changed the authored revision.
        """

        with self._session_factory() as session, session.begin():
            row = session.scalar(
                update(IdentityModel)
                .where(
                    IdentityModel.id == identity_id,
                    IdentityModel.is_frozen.is_(False),
                    IdentityModel.revision == expected_revision,
                )
                .values(**details.model_dump(), revision=expected_revision + 1)
                .returning(IdentityModel)
            )
            if row is None:
                current = session.get(IdentityModel, identity_id)
                if current is None:
                    raise IdentityNotFoundError(str(identity_id))
                if current.is_frozen:
                    raise FrozenIdentityError(
                        "Duplicate this frozen identity to edit it"
                    )
                raise StaleIdentityError("Reload the identity before editing")

            return self._snapshot(row)

    @staticmethod
    def _snapshot(row: IdentityModel) -> Identity:
        """Detach a validated domain snapshot from persistence.

        Args:
            row:
                Persisted identity model.

        Returns:
            An immutable domain identity.
        """

        return Identity(
            id=row.id,
            details=IdentityDetails.model_validate(
                {field: getattr(row, field) for field in IdentityDetails.model_fields}
            ),
            revision=row.revision,
            is_frozen=row.is_frozen,
            is_default=row.default_key is not None,
        )
