"""Explainable evolution inspection and user correction operations."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from chat_buddy.characters.application.evolution_projection_service import (
    EvolutionProjectionService,
)
from chat_buddy.characters.domain import (
    ConversationGraph,
    ConversationGraphRepository,
    ConversationScope,
    EvolutionCommand,
    EvolutionCorrectionAction,
    EvolutionCorrectionEvent,
    EvolutionEffect,
    EvolutionEffectState,
    EvolutionEvent,
    EvolutionEvidence,
    EvolutionEvidenceReference,
    EvolutionProjectionState,
    EvolutionRepository,
    EvolutionScope,
    StartingRelationship,
)


class EvolutionEventInspection(BaseModel):
    """Explainable current disposition of one immutable inferred event.

    Attributes:
        event:
            Original inferred evolution event.
        effective_command:
            Command currently replayed, including a user replacement.
        correction:
            Latest user-authored disposition, when one exists.
        evidence:
            Exact cited exchanges in command order.
        selected:
            Whether every cited exchange is on selected history.
        active:
            Whether the event currently contributes to projection replay.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event: EvolutionEvent = Field(description="Original inferred evolution event.")
    effective_command: EvolutionCommand | None = Field(
        description="Command currently replayed after user correction."
    )
    correction: EvolutionCorrectionEvent | None = Field(
        default=None, description="Latest user-authored disposition."
    )
    evidence: tuple[EvolutionEvidence, ...] = Field(
        description="Exact cited exchanges in command order."
    )
    selected: bool = Field(description="Whether all evidence remains selected.")
    active: bool = Field(description="Whether this event contributes on replay.")


class EvolutionInspection(BaseModel):
    """Complete user-facing evolution state and provenance read model.

    Attributes:
        starting_relationship:
            User-selected relationship state before inference.
        projections:
            Current replayed relationship and adaptation state.
        events:
            Inferred events with correction and branch dispositions.
        rejected_effects:
            Rejected proposals available only to diagnostic presentation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    starting_relationship: StartingRelationship = Field(
        description="User-selected starting relationship state."
    )
    projections: EvolutionProjectionState = Field(
        description="Current replayed relationship and adaptation state."
    )
    events: tuple[EvolutionEventInspection, ...] = Field(
        description="Evolution events with current dispositions."
    )
    rejected_effects: tuple[EvolutionEffect, ...] = Field(
        description="Rejected terminal effects for optional diagnostics."
    )


class EvolutionInspectionService:
    """Assemble explainable evolution state and apply guarded corrections."""

    def __init__(
        self,
        evolution_repository: EvolutionRepository,
        conversation_repository: ConversationGraphRepository,
        projection_service: EvolutionProjectionService,
    ) -> None:
        """Initialize evolution inspection operations.

        Args:
            evolution_repository:
                Evolution projections, events, corrections, and effect audit data.
            conversation_repository:
                Complete graphs used for exact evidence and branch activity.
            projection_service:
                Guarded append-only correction workflow.
        """

        self._evolution_repository = evolution_repository
        self._conversation_repository = conversation_repository
        self._projection_service = projection_service

    def inspect(
        self, scope: EvolutionScope, starting_relationship: StartingRelationship
    ) -> EvolutionInspection:
        """Build a complete inspection view for one continuity.

        Args:
            scope:
                Complete continuity ownership.
            starting_relationship:
                Persisted user-selected starting state.

        Returns:
            Current qualitative state with exact provenance and diagnostics.
        """

        projections = self._evolution_repository.get_projections(scope)
        corrections = self._evolution_repository.list_corrections(scope)
        latest_correction = {
            correction.target_event_id: correction for correction in corrections
        }
        graphs: dict[UUID, ConversationGraph] = {}

        inspected_events = tuple(
            self._inspect_event(event, latest_correction.get(event.id), graphs)
            for event in self._evolution_repository.list_events(scope)
        )
        rejected = tuple(
            effect
            for effect in self._evolution_repository.list_effects(scope)
            if effect.state == EvolutionEffectState.REJECTED
        )

        return EvolutionInspection(
            starting_relationship=starting_relationship,
            projections=projections,
            events=inspected_events,
            rejected_effects=rejected,
        )

    def exclude(
        self,
        inspection: EvolutionInspection,
        event_id: UUID,
        note: str,
    ) -> EvolutionProjectionState:
        """Exclude one inferred event using revisions from an inspected view.

        Args:
            inspection:
                State observed by the user before confirmation.
            event_id:
                Inferred event to exclude.
            note:
                User-authored reason for the correction.

        Returns:
            Corrected projection state.
        """

        return self._projection_service.exclude(
            inspection.projections.relationship.scope,
            event_id,
            inspection.projections.relationship.revision,
            inspection.projections.persona_adaptations.revision,
            note,
        )

    def replace(
        self,
        inspection: EvolutionInspection,
        event_id: UUID,
        replacement: EvolutionCommand,
        note: str,
    ) -> EvolutionProjectionState:
        """Replace one inferred interpretation using observed revisions.

        Args:
            inspection:
                State observed by the user before confirmation.
            event_id:
                Inferred event to correct.
            replacement:
                User-authored command for the same target and evidence.
            note:
                User-authored reason for the correction.

        Returns:
            Corrected projection state.
        """

        return self._projection_service.replace(
            inspection.projections.relationship.scope,
            event_id,
            replacement,
            inspection.projections.relationship.revision,
            inspection.projections.persona_adaptations.revision,
            note,
        )

    def restore(
        self,
        inspection: EvolutionInspection,
        event_id: UUID,
        note: str,
    ) -> EvolutionProjectionState:
        """Restore an excluded or replaced inference using observed revisions.

        Args:
            inspection:
                State observed by the user before confirmation.
            event_id:
                Inferred event to restore.
            note:
                User-authored reason for restoring the inference.

        Returns:
            Corrected projection state.
        """

        return self._projection_service.restore(
            inspection.projections.relationship.scope,
            event_id,
            inspection.projections.relationship.revision,
            inspection.projections.persona_adaptations.revision,
            note,
        )

    def _inspect_event(
        self,
        event: EvolutionEvent,
        correction: EvolutionCorrectionEvent | None,
        graphs: dict[UUID, ConversationGraph],
    ) -> EvolutionEventInspection:
        """Resolve one event's exact evidence and current disposition.

        Args:
            event:
                Original immutable inferred event.
            correction:
                Latest user correction for the event, when present.
            graphs:
                Per-request conversation graph cache.

        Returns:
            Event inspection with exact evidence and replay activity.
        """

        evidence_items = tuple(
            self._evidence(source, graphs) for source in event.command.sources
        )
        selected = all(
            self._source_is_selected(item.reference, graphs) for item in evidence_items
        )
        effective: EvolutionCommand | None = event.command
        if correction is not None:
            if correction.action == EvolutionCorrectionAction.EXCLUDE:
                effective = None
            elif correction.action == EvolutionCorrectionAction.REPLACE:
                effective = correction.replacement

        return EvolutionEventInspection(
            event=event,
            effective_command=effective,
            correction=correction,
            evidence=evidence_items,
            selected=selected,
            active=selected and effective is not None,
        )

    def _evidence(
        self,
        source: EvolutionEvidenceReference,
        graphs: dict[UUID, ConversationGraph],
    ) -> EvolutionEvidence:
        """Resolve exact cited messages from an immutable conversation graph.

        Args:
            source:
                Exact immutable evidence reference.
            graphs:
                Per-request conversation graph cache.

        Returns:
            Exact user and persona content for the cited exchange.
        """

        graph = self._graph(source, graphs)
        nodes = {node.id: node for node in graph.nodes}
        user = nodes[source.user_message_id]
        persona = nodes[source.persona_message_id]

        return EvolutionEvidence(
            reference=source,
            user_content=user.content,
            persona_content=persona.content,
        )

    def _source_is_selected(
        self,
        source: EvolutionEvidenceReference,
        graphs: dict[UUID, ConversationGraph],
    ) -> bool:
        """Return whether one exact adjacent turn remains selected.

        Args:
            source:
                Exact immutable evidence reference.
            graphs:
                Per-request conversation graph cache.

        Returns:
            Whether identifiers and path positions match selected ancestry.
        """

        path = self._graph(source, graphs).selected_path()
        selected_turns = {
            (user.id, position * 2 + 1, persona.id, position * 2 + 2)
            for position, (user, persona) in enumerate(
                zip(path.messages[0::2], path.messages[1::2], strict=False)
            )
        }

        return (
            source.user_message_id,
            source.user_sequence,
            source.persona_message_id,
            source.persona_sequence,
        ) in selected_turns

    def _graph(
        self,
        source: EvolutionEvidenceReference,
        graphs: dict[UUID, ConversationGraph],
    ) -> ConversationGraph:
        """Load and cache one fully owned conversation graph.

        Args:
            source:
                Exact evidence whose conversation is required.
            graphs:
                Per-request conversation graph cache.

        Returns:
            Fully owned immutable graph snapshot.
        """

        graph = graphs.get(source.conversation_id)
        if graph is None:
            graph = self._conversation_repository.graph(
                ConversationScope(
                    identity_id=source.scope.identity_id,
                    persona_id=source.scope.persona_id,
                    continuity_id=source.scope.continuity_id,
                    conversation_id=source.conversation_id,
                )
            )
            graphs[source.conversation_id] = graph

        return graph
