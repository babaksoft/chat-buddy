"""Characters continuity lifecycle and starting-state application rules."""

from itertools import groupby
from uuid import UUID

from chat_buddy.characters.domain import (
    ActiveContinuityError,
    Continuity,
    ContinuityGroup,
    ContinuityMode,
    ContinuityRepository,
    StartContinuity,
    StartingOrigins,
    StartingRelationship,
    UnsupportedContinuityModeError,
)


class ContinuityService:
    """Start, resume, group, and archive isolated Ongoing continuities."""

    def __init__(self, repository: ContinuityRepository) -> None:
        """Bind Characters-owned persistence.

        Args:
            repository:
                Atomic continuity repository.
        """

        self._repository = repository

    def start(self, request: StartContinuity) -> Continuity:
        """Resolve explicit defaults and commit a reviewed confirmation.

        Args:
            request:
                Reviewed profiles and relationship inputs.

        Returns:
            The new or idempotently existing continuity.

        Raises:
            UnsupportedContinuityModeError:
                If the requested mode is not Ongoing.
            ActiveContinuityError:
                If the pair already owns an active Ongoing.
            ConfirmationConflictError:
                If a confirmation identifier is reused with changed inputs.
            StaleIdentityError:
                If an edit changed the reviewed identity revision.
            StalePersonaError:
                If an edit changed the reviewed persona revision.
        """

        if request.mode != ContinuityMode.ONGOING:
            raise UnsupportedContinuityModeError("Only Ongoing is available")
        confirmed = self._repository.find_confirmation(request)
        if confirmed is not None:
            return confirmed
        if (
            self._repository.find_active(request.identity_id, request.persona_id)
            is not None
        ):
            # An identical confirmation may have committed between preflight
            # reads. The transaction repeats every guard for races after this.
            confirmed = self._repository.find_confirmation(request)
            if confirmed is not None:
                return confirmed
            raise ActiveContinuityError(
                "Archive the active Ongoing before starting a replacement"
            )
        selection = request.relationship
        defaults: dict[str, object] = {
            "social": "stranger",
            "romantic": "none",
            "dynamic": "neutral",
            "trust": "unknown",
            "affection": "neutral",
            "boundaries": (),
        }
        origins = {}
        for field, default in defaults.items():
            value = getattr(selection, field)
            defaults[field] = default if value is None else value
            origins[field] = "default" if value is None else "user_selected"
        state = StartingRelationship.model_validate(
            {
                "intent": selection.intent,
                **defaults,
                "origins": StartingOrigins.model_validate(origins),
            }
        )
        return self._repository.start(request, state)

    def resume(
        self, identity_id: UUID, persona_id: UUID, continuity_id: UUID
    ) -> Continuity:
        """Read active or archived history using all ownership identifiers.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            continuity_id:
                Continuity to resume or read.

        Returns:
            The independently owned lifecycle snapshot.
        """

        return self._repository.get(identity_id, persona_id, continuity_id)

    def list_grouped(self) -> tuple[ContinuityGroup, ...]:
        """Group deterministic lifecycle snapshots by identity and persona.

        Returns:
            Ordered ownership groups retaining both active and archived history.
        """

        return tuple(
            ContinuityGroup(
                identity_id=key[0], persona_id=key[1], continuities=tuple(rows)
            )
            for key, rows in groupby(
                self._repository.list(),
                key=lambda row: (row.identity_id, row.persona_id),
            )
        )

    def archive(
        self, identity_id: UUID, persona_id: UUID, continuity_id: UUID
    ) -> Continuity:
        """Make a continuity permanently read-only without unfreezing profiles.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            continuity_id:
                Continuity to archive.

        Returns:
            The archived snapshot.
        """

        return self._repository.archive(identity_id, persona_id, continuity_id)
