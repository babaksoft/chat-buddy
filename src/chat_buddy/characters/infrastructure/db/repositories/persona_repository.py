"""Transactional Characters persona repository."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain.errors import (
    FrozenPersonaError,
    PersonaNotFoundError,
    StalePersonaError,
)
from chat_buddy.characters.domain.persona import Persona, PersonaCore
from chat_buddy.characters.infrastructure.db.models import PersonaModel


class DbPersonaRepository:
    """Persist persona values in repository-owned transactions."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Bind an area-owned session factory.

        Args:
            session_factory:
                Factory for isolated repository transactions.
        """

        self._session_factory = session_factory

    def create(self, core: PersonaCore) -> Persona:
        """Persist a fresh editable persona.

        Args:
            core:
                Validated authored fields.

        Returns:
            The new persisted snapshot.
        """

        with self._session_factory() as session, session.begin():
            row = PersonaModel(**core.model_dump())
            session.add(row)
            session.flush()
            return self._snapshot(row)

    def get(self, persona_id: UUID) -> Persona:
        """Read a detached persona snapshot.

        Args:
            persona_id:
                Stable persona identifier.

        Returns:
            The current persisted snapshot.

        Raises:
            PersonaNotFoundError:
                If the persona does not exist.
        """

        with self._session_factory() as session:
            row = session.get(PersonaModel, persona_id)
            if row is None:
                raise PersonaNotFoundError(str(persona_id))

            return self._snapshot(row)

    def list(self) -> list[Persona]:
        """Read personas in name and UUID order.

        Returns:
            Deterministically ordered snapshots.
        """

        with self._session_factory() as session:
            rows = session.scalars(
                select(PersonaModel).order_by(
                    PersonaModel.name,
                    PersonaModel.id,
                )
            )
            return [self._snapshot(row) for row in rows]

    def replace(
        self, persona_id: UUID, core: PersonaCore, expected_revision: int
    ) -> Persona:
        """Replace fields using a revision/freeze conditional write.

        Args:
            persona_id:
                Stable persona identifier.
            core:
                Validated replacement fields.
            expected_revision:
                Last observed authored revision.

        Returns:
            The updated snapshot.

        Raises:
            PersonaNotFoundError:
                If the persona does not exist.
            FrozenPersonaError:
                If first use froze the persona before this write.
            StalePersonaError:
                If another write changed the authored revision.
        """

        with self._session_factory() as session, session.begin():
            row = session.scalar(
                update(PersonaModel)
                .where(
                    PersonaModel.id == persona_id,
                    PersonaModel.is_frozen.is_(False),
                    PersonaModel.revision == expected_revision,
                )
                .values(**core.model_dump(), revision=expected_revision + 1)
                .returning(PersonaModel)
            )
            if row is None:
                current = session.get(PersonaModel, persona_id)
                if current is None:
                    raise PersonaNotFoundError(str(persona_id))
                if current.is_frozen:
                    raise FrozenPersonaError("Duplicate this frozen persona to edit it")
                raise StalePersonaError("Reload the persona before editing")

            return self._snapshot(row)

    @staticmethod
    def _snapshot(row: PersonaModel) -> Persona:
        """Detach a validated domain snapshot from persistence.

        Args:
            row:
                Persisted persona model.

        Returns:
            An immutable domain persona.
        """

        return Persona(
            id=row.id,
            core=PersonaCore.model_validate(
                {field: getattr(row, field) for field in PersonaCore.model_fields}
            ),
            revision=row.revision,
            is_frozen=row.is_frozen,
        )
