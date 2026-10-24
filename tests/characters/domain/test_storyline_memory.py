"""Executable Storyline memory lifecycle contract tests."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from chat_buddy.characters.domain import (
    ConversationScope,
    CorrectMemoryCommand,
    DeleteMemoryCommand,
    DismissMemoryConflictCommand,
    ExtractionEffect,
    ExtractionEffectState,
    ExtractionProvenance,
    GenerationConfiguration,
    MemoryAuthorship,
    MemoryConflict,
    MemoryConflictState,
    MemoryEvidence,
    MemoryManagementCommand,
    MemoryRevision,
    MemoryRevisionKind,
    MemoryRevisionState,
    ScenePosition,
    StaleMemoryConflictError,
    StorylineMemory,
    StrategyIdentity,
)

NOW = datetime(2026, 10, 24, tzinfo=UTC)


def _scope() -> ConversationScope:
    """Create complete Storyline conversation ownership.

    Returns:
        Valid source ownership.
    """

    return ConversationScope(
        identity_id=uuid4(),
        persona_id=uuid4(),
        continuity_id=uuid4(),
        conversation_id=uuid4(),
    )


def _provenance() -> ExtractionProvenance:
    """Create complete extraction strategy and model provenance.

    Returns:
        Valid immutable extraction provenance.
    """

    return ExtractionProvenance(
        selector=StrategyIdentity(name="baseline.context", version="1.0.0"),
        extractor=StrategyIdentity(name="baseline.delta", version="1.0.0"),
        prompt_schema_version="1.0.0",
        provider="ollama",
        model="local-model",
        configuration=GenerationConfiguration(max_output_tokens=256),
    )


def _evidence(scope: ConversationScope, *, learned_position: int = 2) -> MemoryEvidence:
    """Create exact complete-turn evidence.

    Args:
        scope:
            Source conversation ownership.
        learned_position:
            Source scene ordinal.

    Returns:
        Valid evidence link.
    """

    scene_id = uuid4()
    return MemoryEvidence(
        id=uuid4(),
        scope=scope,
        scene_id=scene_id,
        user_message_id=uuid4(),
        persona_message_id=uuid4(),
        persona_checkpoint=4,
        occurrence=ScenePosition(scene_id=uuid4(), position=1),
        learned=ScenePosition(scene_id=scene_id, position=learned_position),
        extraction=_provenance(),
        created_at=NOW,
    )


def _revision(
    memory_id: UUID,
    evidence: MemoryEvidence,
    *,
    revision: int = 1,
    predecessor_id: UUID | None = None,
    state: MemoryRevisionState = MemoryRevisionState.ACTIVE,
    authorship: MemoryAuthorship = MemoryAuthorship.EXTRACTED,
    kind: MemoryRevisionKind | None = None,
) -> MemoryRevision:
    """Create one owned memory revision.

    Args:
        memory_id:
            Logical-memory identifier.
        evidence:
            Retained originating evidence.
        revision:
            Lineage position.
        predecessor_id:
            Prior revision identifier.
        state:
            Desired lifecycle state.
        authorship:
            Desired content authority.
        kind:
            Optional explicit revision creation operation.

    Returns:
        Valid immutable revision.
    """

    return MemoryRevision(
        id=uuid4(),
        memory_id=memory_id,
        continuity_id=evidence.scope.continuity_id,
        revision=revision,
        predecessor_id=predecessor_id,
        subject="favorite drink",
        content="The user's favorite drink is tea.",
        state=state,
        authorship=authorship,
        kind=kind
        or (
            MemoryRevisionKind.EXTRACTION
            if revision == 1
            else MemoryRevisionKind.USER_CORRECTION
        ),
        source=evidence,
        created_at=NOW + timedelta(minutes=revision),
    )


def test_logical_memory_requires_one_current_revision_and_complete_lineage() -> None:
    """Accept correction lifecycle and reject stale or broken current pointers."""

    scope = _scope()
    evidence = _evidence(scope)
    memory_id = uuid4()
    first = _revision(memory_id, evidence, state=MemoryRevisionState.SUPERSEDED)
    corrected = _revision(
        memory_id,
        evidence,
        revision=2,
        predecessor_id=first.id,
        authorship=MemoryAuthorship.USER,
        kind=MemoryRevisionKind.USER_CORRECTION,
    )
    memory = StorylineMemory(
        id=memory_id,
        continuity_id=scope.continuity_id,
        current_revision_id=corrected.id,
        revisions=(first, corrected),
        evidence=(evidence,),
    )

    assert memory.current == corrected
    assert memory.current.authorship == MemoryAuthorship.USER
    with pytest.raises(ValidationError, match="final lineage revision"):
        StorylineMemory(
            id=memory_id,
            continuity_id=scope.continuity_id,
            current_revision_id=first.id,
            revisions=(first, corrected),
            evidence=(evidence,),
        )
    with pytest.raises(ValidationError, match="Exactly the final"):
        StorylineMemory(
            id=memory_id,
            continuity_id=scope.continuity_id,
            current_revision_id=corrected.id,
            revisions=(first.model_copy(update={"state": "active"}), corrected),
            evidence=(evidence,),
        )


def test_evidence_orders_occurrence_before_learning_and_uses_persona_checkpoint() -> (
    None
):
    """Reject future occurrence positions and non-persona checkpoints."""

    evidence = _evidence(_scope())
    with pytest.raises(ValidationError, match="Occurrence cannot be later"):
        MemoryEvidence.model_validate(
            {
                **evidence.model_dump(),
                "occurrence": {"scene_id": uuid4(), "position": 3},
            }
        )
    with pytest.raises(ValidationError, match="persona messages"):
        MemoryEvidence.model_validate(
            {**evidence.model_dump(), "persona_checkpoint": 3}
        )


def test_exclusion_and_reactivation_retain_interpretation() -> None:
    """Require lifecycle-only revisions to preserve content and provenance."""

    scope = _scope()
    evidence = _evidence(scope)
    memory_id = uuid4()
    extracted = _revision(memory_id, evidence, state=MemoryRevisionState.SUPERSEDED)
    excluded = _revision(
        memory_id,
        evidence,
        revision=2,
        predecessor_id=extracted.id,
        state=MemoryRevisionState.SUPERSEDED,
        kind=MemoryRevisionKind.EXCLUSION,
    )
    reactivated = _revision(
        memory_id,
        evidence,
        revision=3,
        predecessor_id=excluded.id,
        kind=MemoryRevisionKind.REACTIVATION,
    )
    memory = StorylineMemory(
        id=memory_id,
        continuity_id=scope.continuity_id,
        current_revision_id=reactivated.id,
        revisions=(extracted, excluded, reactivated),
        evidence=(evidence,),
    )

    assert memory.current.kind == MemoryRevisionKind.REACTIVATION
    changed = reactivated.model_copy(update={"content": "Changed while excluded."})
    with pytest.raises(ValidationError, match="retain memory interpretation"):
        StorylineMemory(
            id=memory_id,
            continuity_id=scope.continuity_id,
            current_revision_id=changed.id,
            revisions=(extracted, excluded, changed),
            evidence=(evidence,),
        )


def test_reinforcement_evidence_is_distinct_and_continuity_scoped() -> None:
    """Keep supporting evidence unique and inside one Storyline boundary."""

    scope = _scope()
    origin = _evidence(scope)
    memory_id = uuid4()
    revision = _revision(memory_id, origin)
    duplicate_turn = _evidence(scope).model_copy(
        update={"persona_message_id": origin.persona_message_id}
    )

    with pytest.raises(ValidationError, match="only once"):
        StorylineMemory(
            id=memory_id,
            continuity_id=scope.continuity_id,
            current_revision_id=revision.id,
            revisions=(revision,),
            evidence=(origin, duplicate_turn),
        )


def test_conflict_and_effect_lifecycles_are_explicit_and_immutable() -> None:
    """Pair conflict dismissal and extraction completion with their timestamps."""

    scope = _scope()
    evidence = _evidence(scope)
    conflict = MemoryConflict(
        id=uuid4(),
        continuity_id=scope.continuity_id,
        memory_id=uuid4(),
        observed_revision_id=uuid4(),
        proposed_subject="favorite drink",
        proposed_content="The user's favorite drink is coffee.",
        evidence=evidence,
        state=MemoryConflictState.UNRESOLVED,
        created_at=NOW,
        dismissed_at=None,
    )
    effect = ExtractionEffect(
        id=uuid4(),
        scope=scope,
        scene_id=evidence.scene_id,
        source_persona_message_id=evidence.persona_message_id,
        state=ExtractionEffectState.RESERVED,
        provenance=None,
        created_at=NOW,
        completed_at=None,
    )

    assert conflict.state == MemoryConflictState.UNRESOLVED
    assert effect.state == ExtractionEffectState.RESERVED
    with pytest.raises(ValidationError, match="Dismissal time"):
        MemoryConflict.model_validate({**conflict.model_dump(), "state": "dismissed"})
    with pytest.raises(ValidationError, match="completion time"):
        ExtractionEffect.model_validate(
            {**effect.model_dump(), "state": "applied", "provenance": _provenance()}
        )


def test_management_commands_are_bounded_immutable_and_discriminated() -> None:
    """Parse each guarded management action without ambiguous union matching."""

    continuity_id, memory_id, revision_id = uuid4(), uuid4(), uuid4()
    correction = CorrectMemoryCommand(
        continuity_id=continuity_id,
        memory_id=memory_id,
        expected_revision_id=revision_id,
        subject="favorite drink",
        content="The user's favorite drink is coffee.",
    )
    adapter: TypeAdapter[MemoryManagementCommand] = TypeAdapter(MemoryManagementCommand)

    assert adapter.validate_python(correction.model_dump()) == correction
    deletion = adapter.validate_python(
        DeleteMemoryCommand(
            continuity_id=continuity_id,
            memory_id=memory_id,
            expected_revision_id=revision_id,
        ).model_dump()
    )
    assert deletion.operation == "delete"
    with pytest.raises(ValidationError):
        correction.subject = "changed"
    with pytest.raises(ValidationError):
        CorrectMemoryCommand(
            continuity_id=continuity_id,
            memory_id=memory_id,
            expected_revision_id=revision_id,
            subject="s" * 257,
            content="bounded",
        )


def test_conflict_dismissal_guard_matches_optional_target_revision() -> None:
    """Dismiss targeted conflicts with a revision and targetless conflicts without one."""

    scope = _scope()
    evidence = _evidence(scope)
    target_revision_id = uuid4()
    targeted = MemoryConflict(
        id=uuid4(),
        continuity_id=scope.continuity_id,
        memory_id=uuid4(),
        observed_revision_id=target_revision_id,
        proposed_subject="favorite drink",
        proposed_content="The user's favorite drink may be coffee.",
        evidence=evidence,
        state=MemoryConflictState.UNRESOLVED,
        created_at=NOW,
        dismissed_at=None,
    )
    targeted.validate_dismissal(
        DismissMemoryConflictCommand(
            continuity_id=scope.continuity_id,
            conflict_id=targeted.id,
            expected_revision_id=target_revision_id,
        )
    )

    targetless = MemoryConflict(
        id=uuid4(),
        continuity_id=scope.continuity_id,
        memory_id=None,
        observed_revision_id=None,
        proposed_subject=targeted.proposed_subject,
        proposed_content=targeted.proposed_content,
        evidence=evidence,
        state=MemoryConflictState.UNRESOLVED,
        created_at=NOW,
        dismissed_at=None,
    )
    targetless.validate_dismissal(
        DismissMemoryConflictCommand(
            continuity_id=scope.continuity_id,
            conflict_id=targetless.id,
            expected_revision_id=None,
        )
    )
    with pytest.raises(StaleMemoryConflictError, match="observed revision"):
        targetless.validate_dismissal(
            DismissMemoryConflictCommand(
                continuity_id=scope.continuity_id,
                conflict_id=targetless.id,
                expected_revision_id=uuid4(),
            )
        )
