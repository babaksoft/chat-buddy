"""Persistence for continuity-scoped response-style settings."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    ContinuityNotFoundError,
    NarrativePlacement,
    ResponseLength,
    ResponseStyleSettings,
    SceneDescriptionLevel,
    StyleUpdateResult,
    StyleUpdateStatus,
    VersionedResponseStyleSettings,
)
from chat_buddy.characters.infrastructure.db.models import (
    ContinuityModel,
    ResponseStyleSettingsModel,
)


class DbResponseStyleRepository:
    """Read and atomically replace continuity-owned style settings."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory:
                Factory used for short database transactions.
        """

        self._factory = session_factory

    def get(self, continuity_id: UUID) -> VersionedResponseStyleSettings:
        """Read current settings for one continuity.

        Args:
            continuity_id:
                Owning continuity identifier.

        Returns:
            Detached current settings and revision.
        """

        with self._factory() as session:
            row = self._owned(session, continuity_id)
            return self._snapshot(row)

    def update(
        self,
        continuity_id: UUID,
        settings: ResponseStyleSettings,
        expected_revision: int,
    ) -> StyleUpdateResult:
        """Replace all style controls under lifecycle and revision guards.

        Args:
            continuity_id:
                Owning continuity identifier.
            settings:
                Complete replacement settings.
            expected_revision:
                Last observed optimistic revision.

        Returns:
            Explicit update, idempotent, stale, or archived result.
        """

        with self._factory() as session, session.begin():
            continuity = session.scalar(
                select(ContinuityModel)
                .where(ContinuityModel.id == continuity_id)
                .with_for_update()
            )
            if continuity is None:
                raise ContinuityNotFoundError(str(continuity_id))

            row = self._owned(session, continuity_id, lock=True)
            current = self._snapshot(row)
            if continuity.lifecycle != "active":
                return StyleUpdateResult(
                    status=StyleUpdateStatus.ARCHIVED, style=current
                )
            if row.revision != expected_revision:
                return StyleUpdateResult(
                    status=StyleUpdateStatus.STALE_REVISION, style=current
                )
            if current.settings == settings:
                return StyleUpdateResult(
                    status=StyleUpdateStatus.IDEMPOTENT, style=current
                )

            row.scene_description = settings.scene_description.value
            row.response_length = settings.response_length.value
            row.narrative_placement = settings.narrative_placement.value
            row.revision += 1
            session.flush()

            return StyleUpdateResult(
                status=StyleUpdateStatus.UPDATED, style=self._snapshot(row)
            )

    @staticmethod
    def _owned(
        session: Session, continuity_id: UUID, lock: bool = False
    ) -> ResponseStyleSettingsModel:
        """Load one setting row and optionally lock it.

        Args:
            session:
                Current database session.
            continuity_id:
                Expected continuity owner.
            lock:
                Whether to lock the setting row.

        Returns:
            Owned setting row.
        """

        query = select(ResponseStyleSettingsModel).where(
            ResponseStyleSettingsModel.continuity_id == continuity_id
        )
        row = session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise ContinuityNotFoundError(str(continuity_id))

        return row

    @staticmethod
    def _snapshot(row: ResponseStyleSettingsModel) -> VersionedResponseStyleSettings:
        """Build an immutable domain snapshot.

        Args:
            row:
                Persisted setting row.

        Returns:
            Validated detached settings.
        """

        return VersionedResponseStyleSettings(
            settings=ResponseStyleSettings(
                scene_description=SceneDescriptionLevel(row.scene_description),
                response_length=ResponseLength(row.response_length),
                narrative_placement=NarrativePlacement(row.narrative_placement),
            ),
            revision=row.revision,
        )
