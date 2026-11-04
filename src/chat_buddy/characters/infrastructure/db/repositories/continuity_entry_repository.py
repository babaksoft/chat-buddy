"""Read-only persistence for shared Continuity Entry ownership."""

from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    ContinuityEntry,
    ContinuityMode,
    ContinuityNotFoundError,
    ConversationScope,
)
from chat_buddy.characters.infrastructure.db.models import ContinuityEntryModel


class DbContinuityEntryRepository:
    """Read exact immutable Entry ownership and order."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory:
                Factory used for short read transactions.
        """

        self._factory = session_factory

    def get(self, scope: ConversationScope, entry_id: UUID) -> ContinuityEntry:
        """Read one Entry under complete conversation ownership.

        Args:
            scope:
                Expected complete ownership.
            entry_id:
                Stable Entry identifier.

        Returns:
            Exactly owned immutable Entry.

        Raises:
            ContinuityNotFoundError:
                If any ownership component differs.
        """

        with self._factory() as session:
            row = session.scalar(
                select(ContinuityEntryModel).where(
                    ContinuityEntryModel.id == entry_id,
                    ContinuityEntryModel.identity_id == scope.identity_id,
                    ContinuityEntryModel.persona_id == scope.persona_id,
                    ContinuityEntryModel.continuity_id == scope.continuity_id,
                    ContinuityEntryModel.conversation_id == scope.conversation_id,
                )
            )
            if row is None:
                raise ContinuityNotFoundError(str(entry_id))

            return self._snapshot(row)

    def list(
        self,
        identity_id: UUID,
        persona_id: UUID,
        continuity_id: UUID,
        mode: Literal["storyline", "timeline"],
    ) -> tuple[ContinuityEntry, ...]:
        """List exactly owned Entries in immutable position order.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            continuity_id:
                Expected owning continuity.
            mode:
                Expected narrative continuity mode.

        Returns:
            Ordered immutable Entry snapshots.
        """

        with self._factory() as session:
            rows = session.scalars(
                select(ContinuityEntryModel)
                .where(
                    ContinuityEntryModel.identity_id == identity_id,
                    ContinuityEntryModel.persona_id == persona_id,
                    ContinuityEntryModel.continuity_id == continuity_id,
                    ContinuityEntryModel.mode == mode,
                )
                .order_by(ContinuityEntryModel.position)
            )

            return tuple(self._snapshot(row) for row in rows)

    @staticmethod
    def _snapshot(row: ContinuityEntryModel) -> ContinuityEntry:
        """Build a detached Entry snapshot.

        Args:
            row:
                Persisted Entry row.

        Returns:
            Validated immutable Entry.
        """

        return ContinuityEntry(
            id=row.id,
            continuity_id=row.continuity_id,
            identity_id=row.identity_id,
            persona_id=row.persona_id,
            conversation_id=row.conversation_id,
            mode=ContinuityMode(row.mode),
            position=row.position,
        )
