"""Deterministic evolution replay and user-authored correction workflows."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    Continuity,
    ContinuityLifecycle,
    ContinuityNotFoundError,
    ContinuityRepository,
    ConversationGraphRepository,
    ConversationScope,
    EvolutionCommand,
    EvolutionCorrectionAction,
    EvolutionCorrectionConflictError,
    EvolutionCorrectionEvent,
    EvolutionEvent,
    EvolutionProjectionConflictError,
    EvolutionProjectionState,
    EvolutionRepository,
    EvolutionScope,
    PersonaAdaptationProjection,
    RecordRelationshipMilestoneCommand,
    RelationshipAffection,
    RelationshipDynamic,
    RelationshipProjection,
    RelationshipRomanticStatus,
    RelationshipSocialStatus,
    RelationshipTrust,
    RemovePersonaAdaptationCommand,
    SetPersonaAdaptationCommand,
    Storyline,
    StorylineRepository,
    apply_evolution_command,
    is_adaptation_command,
)


class EvolutionProjectionService:
    """Rebuild evolution caches and append guarded user corrections."""

    def __init__(
        self,
        evolution_repository: EvolutionRepository,
        continuity_repository: ContinuityRepository,
        conversation_repository: ConversationGraphRepository,
        storyline_repository: StorylineRepository | None = None,
    ) -> None:
        """Initialize the replay service.

        Args:
            evolution_repository:
                Authoritative events, corrections, and disposable caches.
            continuity_repository:
                Continuity owner and reviewed starting relationship.
            conversation_repository:
                Selected conversation ancestry used to determine active evidence.
            storyline_repository:
                Optional Storyline owner resolver for shared correction workflows.
        """

        self._evolution_repository = evolution_repository
        self._continuity_repository = continuity_repository
        self._conversation_repository = conversation_repository
        self._storyline_repository = storyline_repository

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

        continuity = self._owner(scope)
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

        adaptation_target = is_adaptation_command(target.command)
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

        continuity = self._owner(scope)
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
            if not self._event_is_selected(event):
                continue

            command = dispositions.get(event.id, event.command)
            if is_adaptation_command(event.command):
                adaptation_checkpoint = event.id
            else:
                relationship_checkpoint = event.id
            if command is None:
                continue
            relationship, adaptations = apply_evolution_command(
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

    def _owner(self, scope: EvolutionScope) -> Continuity | Storyline:
        """Resolve an Ongoing or Storyline owner for replay and correction.

        Args:
            scope:
                Complete expected continuity ownership.

        Returns:
            Owned Ongoing or Storyline snapshot.
        """

        try:
            return self._continuity_repository.get(
                scope.identity_id, scope.persona_id, scope.continuity_id
            )
        except ContinuityNotFoundError:
            if self._storyline_repository is None:
                raise

            return self._storyline_repository.get(
                scope.identity_id, scope.persona_id, scope.continuity_id
            )

    def _event_is_selected(self, event: EvolutionEvent) -> bool:
        """Return whether every exact source remains on selected ancestry.

        Args:
            event:
                Immutable inferred event with exact evidence provenance.

        Returns:
            Whether all cited turns remain selected and adjacent.
        """

        selected_turns_by_conversation: dict[UUID, set[tuple[UUID, int, UUID, int]]] = (
            {}
        )

        for source in event.command.sources:
            selected_turns = selected_turns_by_conversation.get(source.conversation_id)
            if selected_turns is None:
                path = self._conversation_repository.selected_path(
                    ConversationScope(
                        identity_id=event.scope.identity_id,
                        persona_id=event.scope.persona_id,
                        continuity_id=event.scope.continuity_id,
                        conversation_id=source.conversation_id,
                    )
                )
                selected_turns = {
                    (
                        user.id,
                        position * 2 + 1,
                        persona.id,
                        position * 2 + 2,
                    )
                    for position, (user, persona) in enumerate(
                        zip(
                            path.messages[0::2],
                            path.messages[1::2],
                            strict=False,
                        )
                    )
                    if user.role == "user"
                    and persona.role == "persona"
                    and persona.parent_id == user.id
                }
                selected_turns_by_conversation[source.conversation_id] = selected_turns

            if (
                source.user_message_id,
                source.user_sequence,
                source.persona_message_id,
                source.persona_sequence,
            ) not in selected_turns:
                return False

        return True

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


def _command_target(command: EvolutionCommand) -> tuple[str, object | None]:
    """Return a stable correction target for one typed command."""

    if isinstance(
        command, (SetPersonaAdaptationCommand, RemovePersonaAdaptationCommand)
    ):
        return "adaptation", command.facet
    if isinstance(command, RecordRelationshipMilestoneCommand):
        return "milestone", None
    return command.kind, None
