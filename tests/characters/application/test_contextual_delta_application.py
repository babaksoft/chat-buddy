"""Post-completion Storyline contextual-delta application tests."""

from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from chat_buddy.characters.application import StorylineMemoryExtractionService
from chat_buddy.characters.domain import (
    ContinuityMode,
    ConversationScope,
    ConversationTarget,
    EffectiveGeneration,
    ExtractionBudget,
    ExtractionEffect,
    ExtractionEffectState,
    ExtractionProvenance,
    GenerationConfiguration,
    InvalidMemoryDeltaTargetError,
    MemoryDelta,
    MemoryRevisionState,
    MemorySubjectConflictError,
    ModelDescriptor,
    NoMemoryChangeCommand,
    StrategyIdentity,
    UnsupportedContinuityModeError,
)


def _scope() -> ConversationScope:
    """Build complete isolated conversation ownership.

    Returns:
        Valid conversation scope.
    """

    return ConversationScope(
        identity_id=uuid4(),
        persona_id=uuid4(),
        continuity_id=uuid4(),
        conversation_id=uuid4(),
    )


def _target(scope: ConversationScope) -> ConversationTarget:
    """Build one Storyline scene target.

    Args:
        scope:
            Complete conversation ownership.

    Returns:
        Valid Storyline target.
    """

    return ConversationTarget(
        scope=scope, mode=ContinuityMode.STORYLINE, scene_id=uuid4()
    )


def _provenance(selector: StrategyIdentity) -> ExtractionProvenance:
    """Build deterministic extraction provenance.

    Args:
        selector:
            Selection strategy used by the snapshot.

    Returns:
        Valid extraction provenance.
    """

    extractor = StrategyIdentity(name="test.extractor", version="1.0.0")
    generation = EffectiveGeneration(
        model=ModelDescriptor(
            provider="test",
            model="memory",
            context_tokens=1024,
            output_tokens=128,
            capabilities=frozenset({"memory_extraction"}),
            parameters=frozenset(),
        ),
        configuration=GenerationConfiguration(max_output_tokens=128),
        capability="memory_extraction",
        input_tokens=896,
    )
    return ExtractionProvenance(
        selector=selector,
        extractor=extractor,
        prompt_schema_version="1.0.0",
        provider=generation.model.provider,
        model=generation.model.model,
        configuration=generation.configuration,
    )


def _effect(
    scope: ConversationScope,
    scene_id: UUID,
    source_id: UUID,
    state: ExtractionEffectState,
    provenance: ExtractionProvenance | None = None,
) -> ExtractionEffect:
    """Build a reserved or terminal effect snapshot.

    Args:
        scope:
            Complete effect ownership.
        scene_id:
            Source scene identifier.
        source_id:
            Source persona-message identifier.
        state:
            Requested effect state.
        provenance:
            Terminal provenance when applicable.

    Returns:
        Valid effect snapshot.
    """

    created_at = datetime.now(UTC)
    return ExtractionEffect(
        id=uuid4(),
        scope=scope,
        scene_id=scene_id,
        source_persona_message_id=source_id,
        state=state,
        provenance=provenance,
        created_at=created_at,
        completed_at=(created_at if state != ExtractionEffectState.RESERVED else None),
    )


def test_process_applies_no_change_once_and_returns_terminal_effect() -> None:
    """Reserve, select, validate, and atomically finish one empty delta."""

    scope = _scope()
    target = _target(scope)
    assert target.scene_id is not None
    source_id = uuid4()
    selector = StrategyIdentity(name="test.selector", version="1.0.0")
    provenance = _provenance(selector)
    selection = Mock()
    selection.id = uuid4()
    selection.selector = selector
    selection.context.scope = scope
    selection.context.source_turn.persona.id = source_id
    delta = MemoryDelta(
        selection_id=selection.id,
        scope=scope,
        source_persona_message_id=source_id,
        extractor=provenance.extractor,
        commands=(NoMemoryChangeCommand(),),
    )
    reserved = _effect(
        scope, target.scene_id, source_id, ExtractionEffectState.RESERVED
    )
    completed = _effect(
        scope,
        target.scene_id,
        source_id,
        ExtractionEffectState.NO_CHANGE,
        provenance,
    )
    contexts = Mock()
    contexts.build.return_value = selection
    extractor = Mock()
    extractor.strategy_id = provenance.extractor
    extractor.extract.return_value = delta
    extractor.provenance.return_value = provenance
    memories = Mock()
    memories.list.return_value = ()
    effects = Mock()
    effects.reserve.return_value = reserved
    effects.apply.return_value = completed
    service = StorylineMemoryExtractionService(
        contexts,
        extractor,
        memories,
        effects,
        ExtractionBudget(input_tokens=512, fixed_overhead_tokens=32),
    )

    assert service.process(target, source_id) == completed
    selection.validate_delta.assert_called_once_with(delta)
    effects.apply.assert_called_once_with(reserved.id, delta, provenance)


def test_terminal_effect_skips_context_and_provider() -> None:
    """Return an existing terminal receipt without repeating interpretation."""

    scope = _scope()
    target = _target(scope)
    assert target.scene_id is not None
    source_id = uuid4()
    selector = StrategyIdentity(name="test.selector", version="1.0.0")
    completed = _effect(
        scope,
        target.scene_id,
        source_id,
        ExtractionEffectState.NO_CHANGE,
        _provenance(selector),
    )
    contexts = Mock()
    extractor = Mock()
    memories = Mock()
    effects = Mock()
    effects.reserve.return_value = completed
    service = StorylineMemoryExtractionService(
        contexts,
        extractor,
        memories,
        effects,
        ExtractionBudget(input_tokens=512, fixed_overhead_tokens=32),
    )

    assert service.process(target, source_id) == completed
    contexts.build.assert_not_called()
    extractor.extract.assert_not_called()
    effects.apply.assert_not_called()


def test_invalid_delta_is_rejected_whole_before_repository_apply() -> None:
    """Leave a reservation retryable when snapshot validation rejects a delta."""

    scope = _scope()
    target = _target(scope)
    assert target.scene_id is not None
    source_id = uuid4()
    selector = StrategyIdentity(name="test.selector", version="1.0.0")
    selection = Mock()
    selection.selector = selector
    selection.validate_delta.side_effect = InvalidMemoryDeltaTargetError("omitted")
    contexts = Mock()
    contexts.build.return_value = selection
    extractor = Mock()
    extractor.extract.return_value = Mock()
    memories = Mock()
    effects = Mock()
    effects.reserve.return_value = _effect(
        scope, target.scene_id, source_id, ExtractionEffectState.RESERVED
    )
    service = StorylineMemoryExtractionService(
        contexts,
        extractor,
        memories,
        effects,
        ExtractionBudget(input_tokens=512, fixed_overhead_tokens=32),
    )

    with pytest.raises(InvalidMemoryDeltaTargetError):
        service.process(target, source_id)

    effects.apply.assert_not_called()


def test_create_cannot_recreate_a_subject_found_only_in_prior_context() -> None:
    """Reject contextual duplication instead of deriving new source evidence."""

    scope = _scope()
    target = _target(scope)
    assert target.scene_id is not None
    source_id = uuid4()
    selector = StrategyIdentity(name="test.selector", version="1.0.0")
    provenance = _provenance(selector)
    selection = Mock()
    selection.selector = selector
    selection.context.scope = scope
    command = Mock()
    command.operation = "create"
    command.subject = "Known preference"
    command.evidence.id = uuid4()
    command.evidence.extraction = provenance
    delta = Mock()
    delta.extractor = provenance.extractor
    delta.commands = (command,)
    contexts = Mock()
    contexts.build.return_value = selection
    extractor = Mock()
    extractor.strategy_id = provenance.extractor
    extractor.extract.return_value = delta
    extractor.provenance.return_value = provenance
    current_memory = Mock()
    current_memory.id = uuid4()
    current_memory.current.subject = "known preference"
    current_memory.current.state = MemoryRevisionState.ACTIVE
    memories = Mock()
    memories.list.return_value = (current_memory,)
    effects = Mock()
    effects.reserve.return_value = _effect(
        scope, target.scene_id, source_id, ExtractionEffectState.RESERVED
    )
    service = StorylineMemoryExtractionService(
        contexts,
        extractor,
        memories,
        effects,
        ExtractionBudget(input_tokens=512, fixed_overhead_tokens=32),
    )

    with pytest.raises(MemorySubjectConflictError):
        service.process(target, source_id)

    effects.apply.assert_not_called()


def test_ongoing_target_never_reserves_or_invokes_extraction() -> None:
    """Reject the memory-free mode before any durable or provider side effect."""

    scope = _scope()
    target = ConversationTarget(scope=scope, mode=ContinuityMode.ONGOING, scene_id=None)
    contexts = Mock()
    extractor = Mock()
    memories = Mock()
    effects = Mock()
    service = StorylineMemoryExtractionService(
        contexts,
        extractor,
        memories,
        effects,
        ExtractionBudget(input_tokens=512, fixed_overhead_tokens=32),
    )

    with pytest.raises(UnsupportedContinuityModeError):
        service.process(target, uuid4())

    effects.reserve.assert_not_called()
    contexts.build.assert_not_called()
    extractor.extract.assert_not_called()
