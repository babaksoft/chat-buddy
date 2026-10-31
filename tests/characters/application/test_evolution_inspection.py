"""Evolution inspection read-model and correction delegation coverage."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

from chat_buddy.characters.application import (
    EvolutionInspectionService,
    EvolutionProjectionService,
)
from chat_buddy.characters.domain import (
    ConversationGraphRepository,
    EvolutionCorrectionAction,
    EvolutionCorrectionEvent,
    EvolutionEvent,
    EvolutionEvidenceKind,
    EvolutionEvidenceReference,
    EvolutionProjectionState,
    EvolutionProvenance,
    EvolutionRepository,
    EvolutionScope,
    PersonaAdaptationProjection,
    RelationshipAffection,
    RelationshipDynamic,
    RelationshipIntent,
    RelationshipProjection,
    RelationshipRomanticStatus,
    RelationshipSocialStatus,
    RelationshipTrust,
    SetSocialStatusCommand,
    StartingOrigins,
    StartingRelationship,
    StrategyIdentity,
)


def test_inspection_distinguishes_inferred_corrected_and_inactive_state() -> None:
    """Resolve exact evidence and preserve correction and branch dispositions."""

    scope = EvolutionScope(
        identity_id=uuid4(), persona_id=uuid4(), continuity_id=uuid4()
    )
    selected_source = _source(scope, uuid4())
    inactive_source = _source(scope, uuid4())
    selected_event = _event(selected_source)
    inactive_event = _event(inactive_source)
    correction = EvolutionCorrectionEvent(
        id=uuid4(),
        scope=scope,
        target_event_id=selected_event.id,
        action=EvolutionCorrectionAction.EXCLUDE,
        note="This exchange was only polite.",
        expected_relationship_revision=2,
        expected_adaptation_revision=0,
        relationship_revision=3,
        adaptation_revision=0,
        created_at=datetime.now(UTC),
    )
    repository = Mock(spec=EvolutionRepository)
    repository.get_projections.return_value = _projections(scope)
    repository.list_events.return_value = (selected_event, inactive_event)
    repository.list_corrections.return_value = (correction,)
    repository.list_effects.return_value = ()
    conversations = Mock(spec=ConversationGraphRepository)
    conversations.graph.side_effect = lambda conversation_scope: _graph(
        (
            selected_source
            if conversation_scope.conversation_id == selected_source.conversation_id
            else inactive_source
        ),
        selected=conversation_scope.conversation_id == selected_source.conversation_id,
    )
    service = EvolutionInspectionService(
        repository, conversations, Mock(spec=EvolutionProjectionService)
    )

    inspection = service.inspect(scope, _starting())

    assert inspection.events[0].correction == correction
    assert inspection.events[0].selected
    assert not inspection.events[0].active
    assert inspection.events[0].effective_command is None
    assert inspection.events[0].evidence[0].user_content == "Exact user evidence"
    assert inspection.events[1].correction is None
    assert not inspection.events[1].selected
    assert not inspection.events[1].active


def test_exclusion_uses_projection_revisions_observed_during_inspection() -> None:
    """Delegate confirmed corrections with optimistic revisions from the view."""

    scope = EvolutionScope(
        identity_id=uuid4(), persona_id=uuid4(), continuity_id=uuid4()
    )
    repository = Mock(spec=EvolutionRepository)
    repository.get_projections.return_value = _projections(scope)
    repository.list_events.return_value = ()
    repository.list_corrections.return_value = ()
    repository.list_effects.return_value = ()
    projections = Mock(spec=EvolutionProjectionService)
    service = EvolutionInspectionService(
        repository, Mock(spec=ConversationGraphRepository), projections
    )
    inspection = service.inspect(scope, _starting())
    event_id = uuid4()

    service.exclude(inspection, event_id, "Do not infer this change.")

    projections.exclude.assert_called_once_with(
        scope,
        event_id,
        2,
        1,
        "Do not infer this change.",
    )


def _source(scope: EvolutionScope, conversation_id: UUID) -> EvolutionEvidenceReference:
    """Build one exact Ongoing evidence reference.

    Args:
        scope:
            Shared evolution ownership.
        conversation_id:
            Unique conversation identifier.

    Returns:
        Exact adjacent source reference.
    """

    return EvolutionEvidenceReference(
        scope=scope,
        kind=EvolutionEvidenceKind.ONGOING_TURN,
        conversation_id=conversation_id,
        user_message_id=uuid4(),
        user_sequence=1,
        persona_message_id=uuid4(),
        persona_sequence=2,
    )


def _event(source: EvolutionEvidenceReference) -> EvolutionEvent:
    """Build one inferred social event.

    Args:
        source:
            Exact evidence cited by the event.

    Returns:
        Immutable inferred event.
    """

    return EvolutionEvent(
        id=uuid4(),
        proposal_id=uuid4(),
        scope=source.scope,
        command=SetSocialStatusCommand(
            expected=RelationshipSocialStatus.STRANGER,
            value=RelationshipSocialStatus.ACQUAINTANCE,
            rationale="The exchange establishes familiarity.",
            sources=(source,),
        ),
        relationship_revision=1,
        adaptation_revision=0,
        provenance=EvolutionProvenance(
            selector=StrategyIdentity(name="selector", version="1.0.0"),
            strategy=StrategyIdentity(name="strategy", version="1.0.0"),
            policy=StrategyIdentity(name="policy", version="1.0.0"),
            schema_identity=StrategyIdentity(name="schema", version="1.0.0"),
        ),
        created_at=datetime.now(UTC),
    )


def _projections(scope: EvolutionScope) -> EvolutionProjectionState:
    """Build current paired projection caches.

    Args:
        scope:
            Shared evolution ownership.

    Returns:
        Qualitative relationship and adaptation projections.
    """

    return EvolutionProjectionState(
        relationship=RelationshipProjection(
            scope=scope,
            revision=2,
            social=RelationshipSocialStatus.ACQUAINTANCE,
            romantic=RelationshipRomanticStatus.NONE,
            dynamic=RelationshipDynamic.COMFORTABLE,
            trust=RelationshipTrust.CAUTIOUS,
            affection=RelationshipAffection.WARM,
        ),
        persona_adaptations=PersonaAdaptationProjection(scope=scope, revision=1),
        updated_at=datetime.now(UTC),
    )


def _starting() -> StartingRelationship:
    """Build a user-selected replay baseline.

    Returns:
        Starting qualitative relationship state.
    """

    return StartingRelationship(
        intent=RelationshipIntent.NATURAL,
        social="stranger",
        romantic="none",
        dynamic="neutral",
        trust="unknown",
        affection="neutral",
        boundaries=(),
        origins=StartingOrigins(
            social="user_selected",
            romantic="default",
            dynamic="default",
            trust="default",
            affection="default",
            boundaries="default",
        ),
    )


def _graph(source: EvolutionEvidenceReference, selected: bool) -> SimpleNamespace:
    """Build a minimal graph double with exact and selected nodes.

    Args:
        source:
            Evidence reference represented by the graph.
        selected:
            Whether the exact exchange remains selected.

    Returns:
        Graph-shaped double used by the inspection service.
    """

    user = SimpleNamespace(id=source.user_message_id, content="Exact user evidence")
    persona = SimpleNamespace(
        id=source.persona_message_id, content="Exact persona evidence"
    )
    path = SimpleNamespace(messages=(user, persona) if selected else ())
    return SimpleNamespace(nodes=(user, persona), selected_path=lambda: path)
