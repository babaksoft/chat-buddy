"""Storyline memory and extraction repository integration coverage."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    ConversationScope,
    CreateMemoryCommand,
    DeleteMemoryCommand,
    DismissMemoryConflictCommand,
    ExtractionEffectConflictError,
    ExtractionEffectState,
    ExtractionProvenance,
    GenerationConfiguration,
    InvalidMemoryDeltaTargetError,
    MemoryConflictState,
    MemoryDelta,
    MemoryEvidence,
    MemoryNotFoundError,
    NoMemoryChangeCommand,
    RecordMemoryConflictCommand,
    ReinforceMemoryCommand,
    ScenePosition,
    StaleMemoryRevisionError,
    StrategyIdentity,
    SupersedeMemoryCommand,
)
from chat_buddy.characters.infrastructure.db.models import (
    ConversationModel,
    MessageModel,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbMemoryExtractionRepository,
    DbStorylineMemoryRepository,
)
from tests.integration.characters.test_storyline_repositories import (
    _complete_exchange,
    _relationship,
    _repositories_and_request,
)


def test_create_reinforce_read_eligibility_and_hard_delete_round_trip(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Persist lineages and unique evidence, then remove the complete lineage.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    storylines, _, request = _repositories_and_request(factory)
    storyline, scene = storylines.start(request, _relationship())
    first_persona_id = _complete_exchange(
        factory, scene.scope.conversation_id, storyline.id
    )
    first_user_id = _parent_id(factory, first_persona_id)
    extraction = DbMemoryExtractionRepository(factory)
    memories = DbStorylineMemoryRepository(factory)
    provenance = _provenance()

    reserved = extraction.reserve(scene.scope, scene.id, first_persona_id)
    assert reserved.state == ExtractionEffectState.RESERVED
    assert extraction.reserve(scene.scope, scene.id, first_persona_id) == reserved
    evidence = _evidence(
        scene.scope, scene.id, first_user_id, first_persona_id, 2, provenance
    )
    applied = extraction.apply(
        reserved.id,
        MemoryDelta(
            selection_id=uuid4(),
            scope=scene.scope,
            source_persona_message_id=first_persona_id,
            extractor=provenance.extractor,
            commands=(
                CreateMemoryCommand(
                    subject="departure time",
                    content="The train leaves at midnight.",
                    occurrence=evidence.occurrence,
                    evidence=evidence,
                ),
            ),
        ),
        provenance,
    )
    assert applied.state == ExtractionEffectState.APPLIED
    assert applied.provenance == provenance

    (memory,) = memories.list(storyline.id)
    assert memories.get(storyline.id, memory.id) == memory
    assert memory.current.subject == "departure time"
    assert memory.current.content == "The train leaves at midnight."
    assert memories.list_eligible(storyline.id, 1, frozenset({first_persona_id})) == (
        memory,
    )
    assert memories.list_eligible(storyline.id, 1, frozenset()) == ()

    second_user_id, second_persona_id = _append_exchange(factory, scene.scope)
    second_reserved = extraction.reserve(scene.scope, scene.id, second_persona_id)
    second_evidence = _evidence(
        scene.scope,
        scene.id,
        second_user_id,
        second_persona_id,
        4,
        provenance,
    )
    extraction.apply(
        second_reserved.id,
        MemoryDelta(
            selection_id=uuid4(),
            scope=scene.scope,
            source_persona_message_id=second_persona_id,
            extractor=provenance.extractor,
            commands=(
                ReinforceMemoryCommand(
                    target_memory_id=memory.id,
                    expected_revision_id=memory.current.id,
                    content=memory.current.content,
                    evidence=second_evidence,
                ),
            ),
        ),
        provenance,
    )
    reinforced = memories.get(storyline.id, memory.id)
    assert len(reinforced.revisions) == 1
    assert tuple(item.persona_message_id for item in reinforced.evidence) == (
        first_persona_id,
        second_persona_id,
    )

    with pytest.raises(StaleMemoryRevisionError):
        memories.delete(
            DeleteMemoryCommand(
                continuity_id=storyline.id,
                memory_id=memory.id,
                expected_revision_id=uuid4(),
            )
        )
    memories.delete(
        DeleteMemoryCommand(
            continuity_id=storyline.id,
            memory_id=memory.id,
            expected_revision_id=memory.current.id,
        )
    )
    with pytest.raises(MemoryNotFoundError):
        memories.get(storyline.id, memory.id)


def test_reservation_and_apply_reject_foreign_or_stale_sources(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Reject foreign scope, terminal reuse, and stale delta targets atomically.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    storylines, _, request = _repositories_and_request(factory)
    storyline, scene = storylines.start(request, _relationship())
    persona_id = _complete_exchange(factory, scene.scope.conversation_id, storyline.id)
    extraction = DbMemoryExtractionRepository(factory)
    provenance = _provenance()

    with pytest.raises(ExtractionEffectConflictError):
        extraction.reserve(
            scene.scope.model_copy(update={"identity_id": uuid4()}),
            scene.id,
            persona_id,
        )

    effect = extraction.reserve(scene.scope, scene.id, persona_id)
    evidence = _evidence(
        scene.scope,
        scene.id,
        _parent_id(factory, persona_id),
        persona_id,
        2,
        provenance,
    )
    created = extraction.apply(
        effect.id,
        MemoryDelta(
            selection_id=uuid4(),
            scope=scene.scope,
            source_persona_message_id=persona_id,
            extractor=provenance.extractor,
            commands=(
                CreateMemoryCommand(
                    subject="ticket",
                    content="The ticket is blue.",
                    occurrence=evidence.occurrence,
                    evidence=evidence,
                ),
            ),
        ),
        provenance,
    )
    assert extraction.get_effect(scene.scope, persona_id) == created
    with pytest.raises(ExtractionEffectConflictError):
        extraction.apply(
            effect.id,
            MemoryDelta(
                selection_id=uuid4(),
                scope=scene.scope,
                source_persona_message_id=persona_id,
                extractor=provenance.extractor,
                commands=(
                    CreateMemoryCommand(
                        subject="other",
                        content="This cannot commit.",
                        occurrence=evidence.occurrence,
                        evidence=evidence.model_copy(update={"id": uuid4()}),
                    ),
                ),
            ),
            provenance,
        )

    memory = DbStorylineMemoryRepository(factory).list(storyline.id)[0]
    user_id, next_persona_id = _append_exchange(factory, scene.scope)
    next_effect = extraction.reserve(scene.scope, scene.id, next_persona_id)
    next_evidence = _evidence(
        scene.scope, scene.id, user_id, next_persona_id, 4, provenance
    )
    with pytest.raises(InvalidMemoryDeltaTargetError):
        extraction.apply(
            next_effect.id,
            MemoryDelta(
                selection_id=uuid4(),
                scope=scene.scope,
                source_persona_message_id=next_persona_id,
                extractor=provenance.extractor,
                commands=(
                    ReinforceMemoryCommand(
                        target_memory_id=memory.id,
                        expected_revision_id=uuid4(),
                        content=memory.current.content,
                        evidence=next_evidence,
                    ),
                ),
            ),
            provenance,
        )
    pending = extraction.get_effect(scene.scope, next_persona_id)
    assert pending is not None
    assert pending.state == ExtractionEffectState.RESERVED


def test_supersede_conflict_dismissal_and_no_change_records_round_trip(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Persist every terminal effect and conflict record without partial writes.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    storylines, _, request = _repositories_and_request(factory)
    storyline, scene = storylines.start(request, _relationship())
    extraction = DbMemoryExtractionRepository(factory)
    memories = DbStorylineMemoryRepository(factory)
    provenance = _provenance()

    first_persona_id = _complete_exchange(
        factory, scene.scope.conversation_id, storyline.id
    )
    first_evidence = _evidence(
        scene.scope,
        scene.id,
        _parent_id(factory, first_persona_id),
        first_persona_id,
        2,
        provenance,
    )
    first_effect = extraction.reserve(scene.scope, scene.id, first_persona_id)
    extraction.apply(
        first_effect.id,
        MemoryDelta(
            selection_id=uuid4(),
            scope=scene.scope,
            source_persona_message_id=first_persona_id,
            extractor=provenance.extractor,
            commands=(
                CreateMemoryCommand(
                    subject="departure time",
                    content="The train leaves at midnight.",
                    occurrence=first_evidence.occurrence,
                    evidence=first_evidence,
                ),
            ),
        ),
        provenance,
    )
    initial = memories.list(storyline.id)[0]

    second_user_id, second_persona_id = _append_exchange(factory, scene.scope)
    second_evidence = _evidence(
        scene.scope,
        scene.id,
        second_user_id,
        second_persona_id,
        4,
        provenance,
    )
    second_effect = extraction.reserve(scene.scope, scene.id, second_persona_id)
    extraction.apply(
        second_effect.id,
        MemoryDelta(
            selection_id=uuid4(),
            scope=scene.scope,
            source_persona_message_id=second_persona_id,
            extractor=provenance.extractor,
            commands=(
                SupersedeMemoryCommand(
                    target_memory_id=initial.id,
                    expected_revision_id=initial.current.id,
                    subject="departure time",
                    content="The train now leaves at one in the morning.",
                    occurrence=second_evidence.occurrence,
                    evidence=second_evidence,
                ),
            ),
        ),
        provenance,
    )
    superseded = memories.get(storyline.id, initial.id)
    assert tuple(revision.state for revision in superseded.revisions) == (
        "superseded",
        "active",
    )
    assert superseded.current.predecessor_id == initial.current.id

    third_user_id, third_persona_id = _append_exchange(factory, scene.scope)
    third_evidence = _evidence(
        scene.scope,
        scene.id,
        third_user_id,
        third_persona_id,
        6,
        provenance,
    )
    third_effect = extraction.reserve(scene.scope, scene.id, third_persona_id)
    extraction.apply(
        third_effect.id,
        MemoryDelta(
            selection_id=uuid4(),
            scope=scene.scope,
            source_persona_message_id=third_persona_id,
            extractor=provenance.extractor,
            commands=(
                RecordMemoryConflictCommand(
                    target_memory_id=superseded.id,
                    expected_revision_id=superseded.current.id,
                    subject="departure time dispute",
                    content="A station clock still shows midnight.",
                    occurrence=third_evidence.occurrence,
                    evidence=third_evidence,
                ),
            ),
        ),
        provenance,
    )
    (conflict,) = extraction.list_conflicts(storyline.id)
    assert conflict.state == MemoryConflictState.UNRESOLVED
    dismissed = extraction.dismiss_conflict(
        DismissMemoryConflictCommand(
            continuity_id=storyline.id,
            conflict_id=conflict.id,
            expected_revision_id=superseded.current.id,
        )
    )
    assert dismissed.state == MemoryConflictState.DISMISSED
    assert dismissed.dismissed_at is not None

    _, fourth_persona_id = _append_exchange(factory, scene.scope)
    fourth_effect = extraction.reserve(scene.scope, scene.id, fourth_persona_id)
    no_change = extraction.apply(
        fourth_effect.id,
        MemoryDelta(
            selection_id=uuid4(),
            scope=scene.scope,
            source_persona_message_id=fourth_persona_id,
            extractor=provenance.extractor,
            commands=(NoMemoryChangeCommand(),),
        ),
        provenance,
    )
    assert no_change.state == ExtractionEffectState.NO_CHANGE
    assert no_change.provenance == provenance


def _append_exchange(
    factory: sessionmaker[Session], scope: ConversationScope
) -> tuple[UUID, UUID]:
    """Append and select another complete exchange in the test graph.

    Args:
        factory:
            Isolated database factory.
        scope:
            Owned conversation scope.

    Returns:
        New user and persona identifiers.
    """

    now = datetime.now(UTC)
    with factory() as session, session.begin():
        conversation = session.get(ConversationModel, scope.conversation_id)
        assert conversation is not None
        user = MessageModel(
            conversation_id=scope.conversation_id,
            continuity_id=scope.continuity_id,
            role="user",
            content="Midnight, right?",
            parent_id=conversation.selected_leaf_id,
            created_at=now,
        )
        session.add(user)
        session.flush()
        persona = MessageModel(
            conversation_id=scope.conversation_id,
            continuity_id=scope.continuity_id,
            role="persona",
            content="Yes, midnight.",
            parent_id=user.id,
            response_provenance={"test": True},
            created_at=now,
        )
        session.add(persona)
        session.flush()
        conversation.selected_leaf_id = persona.id
        return user.id, persona.id


def _parent_id(factory: sessionmaker[Session], persona_id: UUID) -> UUID:
    """Return a test persona message's required user parent.

    Args:
        factory:
            Isolated database factory.
        persona_id:
            Persona checkpoint identifier.

    Returns:
        Parent user-message identifier.
    """

    with factory() as session:
        parent_id = session.scalar(
            select(MessageModel.parent_id).where(MessageModel.id == persona_id)
        )
        assert parent_id is not None
        return parent_id


def _provenance() -> ExtractionProvenance:
    """Build complete deterministic extraction provenance.

    Returns:
        Valid extraction provenance.
    """

    return ExtractionProvenance(
        selector=StrategyIdentity(name="whole_record", version="1.0.0"),
        extractor=StrategyIdentity(name="contextual_delta", version="1.0.0"),
        prompt_schema_version="1.0.0",
        provider="fake",
        model="memory-test",
        configuration=GenerationConfiguration(max_output_tokens=256, temperature=0),
    )


def _evidence(
    scope: ConversationScope,
    scene_id: UUID,
    user_id: UUID,
    persona_id: UUID,
    checkpoint: int,
    provenance: ExtractionProvenance,
) -> MemoryEvidence:
    """Build source evidence for the sole first-scene test setup.

    Args:
        scope:
            Complete source ownership.
        scene_id:
            Source and occurrence scene.
        user_id:
            Source user-message identifier.
        persona_id:
            Source persona checkpoint.
        checkpoint:
            Even selected-path position.
        provenance:
            Extraction configuration.

    Returns:
        Valid immutable evidence.
    """

    position = ScenePosition(scene_id=scene_id, position=1)
    return MemoryEvidence(
        id=uuid4(),
        scope=scope,
        scene_id=scene_id,
        user_message_id=user_id,
        persona_message_id=persona_id,
        persona_checkpoint=checkpoint,
        occurrence=position,
        learned=position,
        extraction=provenance,
        created_at=datetime.now(UTC),
    )
