"""Deterministic evolution replay and user-authored correction workflows."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    ContinuityLifecycle,
    ContinuityRepository,
    EvolutionCommand,
    EvolutionCorrectionAction,
    EvolutionCorrectionConflictError,
    EvolutionCorrectionEvent,
    EvolutionEvent,
    EvolutionProjectionConflictError,
    EvolutionProjectionState,
    EvolutionRepository,
    EvolutionScope,
    PersonaAdaptation,
    PersonaAdaptationProjection,
    RecordRelationshipMilestoneCommand,
    RelationshipAffection,
    RelationshipDynamic,
    RelationshipProjection,
    RelationshipRomanticStatus,
    RelationshipSocialStatus,
    RelationshipTrust,
    RemovePersonaAdaptationCommand,
    SetAffectionCommand,
    SetDynamicCommand,
    SetPersonaAdaptationCommand,
    SetRomanticStatusCommand,
    SetSocialStatusCommand,
    SetTrustCommand,
)


class EvolutionProjectionService:
    """Rebuild evolution caches and append guarded user corrections."""

    def __init__(
        self,
        evolution_repository: EvolutionRepository,
        continuity_repository: ContinuityRepository,
    ) -> None:
        """Initialize the replay service.

        Args:
            evolution_repository:
                Authoritative events, corrections, and disposable caches.
            continuity_repository:
                Continuity owner and reviewed starting relationship.
        """

        self._evolution_repository = evolution_repository
        self._continuity_repository = continuity_repository

    def rebuild(
        self,
        scope: EvolutionScope,
        expected_relationship_revision: int | None = None,
        expected_adaptation_revision: int | None = None,
    ) -> EvolutionProjectionState:
        """Replay all authoritative history and replace or recreate both caches.

        Args:
            scope:
                Complete continuity ownership.
            expected_relationship_revision:
                Optional observed relationship revision for guarded replacement.
            expected_adaptation_revision:
                Optional observed adaptation revision for guarded replacement.

        Returns:
            Fully replayed persisted projection state.
        """

        if (expected_relationship_revision is None) != (
            expected_adaptation_revision is None
        ):
            raise EvolutionProjectionConflictError(
                "Evolution rebuild requires both observed revisions"
            )

        replayed, relationship_checkpoint, adaptation_checkpoint = self._replay(scope)
        return self._evolution_repository.rebuild_projections(
            replayed.relationship,
            replayed.persona_adaptations,
            relationship_checkpoint,
            adaptation_checkpoint,
            expected_relationship_revision,
            expected_adaptation_revision,
        )

    def exclude(
        self,
        scope: EvolutionScope,
        target_event_id: UUID,
        expected_relationship_revision: int,
        expected_adaptation_revision: int,
        note: str,
    ) -> EvolutionProjectionState:
        """Exclude one inferred interpretation and rebuild dependent later state.

        Args:
            scope:
                Complete continuity ownership.
            target_event_id:
                Immutable inferred event to exclude.
            expected_relationship_revision:
                Relationship revision observed by the user.
            expected_adaptation_revision:
                Adaptation revision observed by the user.
            note:
                Concise user-authored reason.

        Returns:
            Corrected persisted projection state.
        """

        return self._correct(
            scope,
            target_event_id,
            EvolutionCorrectionAction.EXCLUDE,
            None,
            expected_relationship_revision,
            expected_adaptation_revision,
            note,
        )

    def replace(
        self,
        scope: EvolutionScope,
        target_event_id: UUID,
        replacement: EvolutionCommand,
        expected_relationship_revision: int,
        expected_adaptation_revision: int,
        note: str,
    ) -> EvolutionProjectionState:
        """Replace one inferred relationship or adaptation interpretation.

        Args:
            scope:
                Complete continuity ownership.
            target_event_id:
                Immutable inferred event to replace.
            replacement:
                User-authored command for the same target.
            expected_relationship_revision:
                Relationship revision observed by the user.
            expected_adaptation_revision:
                Adaptation revision observed by the user.
            note:
                Concise user-authored reason.

        Returns:
            Corrected persisted projection state.
        """

        return self._correct(
            scope,
            target_event_id,
            EvolutionCorrectionAction.REPLACE,
            replacement,
            expected_relationship_revision,
            expected_adaptation_revision,
            note,
        )

    def restore(
        self,
        scope: EvolutionScope,
        target_event_id: UUID,
        expected_relationship_revision: int,
        expected_adaptation_revision: int,
        note: str,
    ) -> EvolutionProjectionState:
        """Restore an inferred interpretation after exclusion or replacement.

        Args:
            scope:
                Complete continuity ownership.
            target_event_id:
                Immutable inferred event to restore.
            expected_relationship_revision:
                Relationship revision observed by the user.
            expected_adaptation_revision:
                Adaptation revision observed by the user.
            note:
                Concise user-authored reason.

        Returns:
            Corrected persisted projection state.
        """

        return self._correct(
            scope,
            target_event_id,
            EvolutionCorrectionAction.RESTORE,
            None,
            expected_relationship_revision,
            expected_adaptation_revision,
            note,
        )

    def _correct(
        self,
        scope: EvolutionScope,
        target_event_id: UUID,
        action: EvolutionCorrectionAction,
        replacement: EvolutionCommand | None,
        expected_relationship_revision: int,
        expected_adaptation_revision: int,
        note: str,
    ) -> EvolutionProjectionState:
        """Validate, append, and replay one user-authored correction."""

        continuity = self._continuity_repository.get(
            scope.identity_id, scope.persona_id, scope.continuity_id
        )
        if continuity.lifecycle == ContinuityLifecycle.ARCHIVED:
            raise ArchivedContinuityError("Archived continuities cannot be corrected")

        events = self._evolution_repository.list_events(scope)
        target = next((event for event in events if event.id == target_event_id), None)
        if target is None:
            raise EvolutionCorrectionConflictError(
                "Evolution correction target does not exist"
            )

        if replacement is not None:
            self._validate_replacement(target.command, replacement, scope)

        corrections = self._evolution_repository.list_corrections(scope)
        prior = tuple(
            correction
            for correction in corrections
            if correction.target_event_id == target_event_id
        )
        if action == EvolutionCorrectionAction.RESTORE and (
            not prior or prior[-1].action == EvolutionCorrectionAction.RESTORE
        ):
            raise EvolutionCorrectionConflictError(
                "Only an excluded or replaced interpretation can be restored"
            )

        adaptation_target = _is_adaptation(target.command)
        correction = EvolutionCorrectionEvent(
            id=uuid4(),
            scope=scope,
            target_event_id=target_event_id,
            action=action,
            replacement=replacement,
            note=note,
            expected_relationship_revision=expected_relationship_revision,
            expected_adaptation_revision=expected_adaptation_revision,
            relationship_revision=(
                expected_relationship_revision + (not adaptation_target)
            ),
            adaptation_revision=(expected_adaptation_revision + adaptation_target),
            created_at=datetime.now(UTC),
        )
        replayed, _, _ = self._replay(
            scope, events=events, corrections=(*corrections, correction)
        )

        return self._evolution_repository.append_correction(
            correction, replayed.relationship, replayed.persona_adaptations
        )

    def _replay(
        self,
        scope: EvolutionScope,
        events: tuple[EvolutionEvent, ...] | None = None,
        corrections: tuple[EvolutionCorrectionEvent, ...] | None = None,
    ) -> tuple[EvolutionProjectionState, UUID | None, UUID | None]:
        """Derive both projections and inferred checkpoints from history."""

        continuity = self._continuity_repository.get(
            scope.identity_id, scope.persona_id, scope.continuity_id
        )
        inferred = (
            self._evolution_repository.list_events(scope) if events is None else events
        )
        authored = (
            self._evolution_repository.list_corrections(scope)
            if corrections is None
            else corrections
        )
        dispositions: dict[UUID, EvolutionCommand | None] = {}

        for correction in authored:
            if correction.action == EvolutionCorrectionAction.RESTORE:
                dispositions.pop(correction.target_event_id, None)
            elif correction.action == EvolutionCorrectionAction.EXCLUDE:
                dispositions[correction.target_event_id] = None
            else:
                dispositions[correction.target_event_id] = correction.replacement

        starting = continuity.relationship
        relationship = RelationshipProjection(
            scope=scope,
            revision=0,
            social=RelationshipSocialStatus(starting.social),
            romantic=RelationshipRomanticStatus(starting.romantic),
            dynamic=RelationshipDynamic(starting.dynamic),
            trust=RelationshipTrust(starting.trust),
            affection=RelationshipAffection(starting.affection),
        )
        adaptations = PersonaAdaptationProjection(scope=scope, revision=0)
        relationship_checkpoint: UUID | None = None
        adaptation_checkpoint: UUID | None = None

        for event in inferred:
            command = dispositions.get(event.id, event.command)
            if _is_adaptation(event.command):
                adaptation_checkpoint = event.id
            else:
                relationship_checkpoint = event.id
            if command is None:
                continue
            relationship, adaptations = _apply_command(
                relationship, adaptations, command
            )

        history: tuple[EvolutionEvent | EvolutionCorrectionEvent, ...] = (
            *inferred,
            *authored,
        )
        relationship_revision = max(
            (item.relationship_revision for item in history), default=0
        )
        adaptation_revision = max(
            (item.adaptation_revision for item in history), default=0
        )
        relationship = relationship.model_copy(
            update={"revision": relationship_revision}
        )
        adaptations = adaptations.model_copy(update={"revision": adaptation_revision})

        return (
            EvolutionProjectionState(
                relationship=relationship,
                persona_adaptations=adaptations,
                relationship_checkpoint_id=relationship_checkpoint,
                adaptation_checkpoint_id=adaptation_checkpoint,
                updated_at=datetime.now(UTC),
            ),
            relationship_checkpoint,
            adaptation_checkpoint,
        )

    @staticmethod
    def _validate_replacement(
        target: EvolutionCommand,
        replacement: EvolutionCommand,
        scope: EvolutionScope,
    ) -> None:
        """Require a correction to preserve the inferred target and provenance."""

        if _command_target(target) != _command_target(replacement):
            raise EvolutionCorrectionConflictError(
                "Evolution replacement must correct the same target"
            )
        if target.sources != replacement.sources or any(
            source.scope != scope for source in replacement.sources
        ):
            raise EvolutionCorrectionConflictError(
                "Evolution replacement must retain exact source provenance"
            )


def _apply_command(
    relationship: RelationshipProjection,
    adaptations: PersonaAdaptationProjection,
    command: EvolutionCommand,
) -> tuple[RelationshipProjection, PersonaAdaptationProjection]:
    """Apply one replay-eligible command when its expected state still matches."""

    if isinstance(command, SetSocialStatusCommand):
        if relationship.social == command.expected:
            relationship = relationship.model_copy(update={"social": command.value})
    elif isinstance(command, SetRomanticStatusCommand):
        if relationship.romantic == command.expected:
            relationship = relationship.model_copy(update={"romantic": command.value})
    elif isinstance(command, SetDynamicCommand):
        if relationship.dynamic == command.expected:
            relationship = relationship.model_copy(update={"dynamic": command.value})
    elif isinstance(command, SetTrustCommand):
        if relationship.trust == command.expected:
            relationship = relationship.model_copy(update={"trust": command.value})
    elif isinstance(command, SetAffectionCommand):
        if relationship.affection == command.expected:
            relationship = relationship.model_copy(update={"affection": command.value})
    elif isinstance(command, RecordRelationshipMilestoneCommand):
        if relationship.romantic == command.expected:
            milestones = relationship.milestones
            if command.milestone not in milestones:
                milestones = (*milestones, command.milestone)
            relationship = relationship.model_copy(
                update={"romantic": command.value, "milestones": milestones}
            )
    elif isinstance(command, SetPersonaAdaptationCommand):
        current = {item.facet: item for item in adaptations.adaptations}
        observed = current.get(command.facet)
        if (observed.value if observed is not None else None) == command.expected:
            current[command.facet] = PersonaAdaptation(
                facet=command.facet, value=command.value
            )
            adaptations = adaptations.model_copy(
                update={
                    "adaptations": tuple(
                        current[facet] for facet in sorted(current, key=str)
                    )
                }
            )
    elif isinstance(command, RemovePersonaAdaptationCommand):
        current = {item.facet: item for item in adaptations.adaptations}
        observed = current.get(command.facet)
        if observed is not None and observed.value == command.expected:
            current.pop(command.facet)
            adaptations = adaptations.model_copy(
                update={
                    "adaptations": tuple(
                        current[facet] for facet in sorted(current, key=str)
                    )
                }
            )

    return relationship, adaptations


def _is_adaptation(command: EvolutionCommand) -> bool:
    """Return whether a command targets persona adaptation state."""

    return isinstance(
        command, (SetPersonaAdaptationCommand, RemovePersonaAdaptationCommand)
    )


def _command_target(command: EvolutionCommand) -> tuple[str, object | None]:
    """Return a stable correction target for one typed command."""

    if isinstance(
        command, (SetPersonaAdaptationCommand, RemovePersonaAdaptationCommand)
    ):
        return "adaptation", command.facet
    if isinstance(command, RecordRelationshipMilestoneCommand):
        return "milestone", None
    return command.kind, None
