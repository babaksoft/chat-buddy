"""Streamlit acceptance tests for Storyline memory controls."""

from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from streamlit.testing.v1 import AppTest

from chat_buddy.characters.application import StorylineMemoryService
from chat_buddy.characters.domain import (
    ChangeMemoryStateCommand,
    ContinuityLifecycle,
    ConversationScope,
    CorrectMemoryCommand,
    DeleteMemoryCommand,
    DismissMemoryConflictCommand,
    ExtractionProvenance,
    GenerationConfiguration,
    MemoryAuthorship,
    MemoryConflict,
    MemoryConflictState,
    MemoryEvidence,
    MemoryRevision,
    MemoryRevisionKind,
    MemoryRevisionState,
    ScenePosition,
    StaleMemoryRevisionError,
    Storyline,
    StorylineMemory,
    StrategyIdentity,
)

NOW = datetime(2026, 10, 27, tzinfo=UTC)
SELECTED_LEAF_ID = UUID("00000000-0000-0000-0000-000000000017")


def _render(service: object, storyline: object, selected_leaf_id: object) -> None:
    """Render the focused memory view through the test harness.

    Args:
        service:
            Memory service passed through Streamlit's isolated runner.
        storyline:
            Storyline passed through Streamlit's isolated runner.
        selected_leaf_id:
            Branch checkpoint passed through Streamlit's isolated runner.
    """

    from typing import cast
    from uuid import UUID

    from chat_buddy.characters.application import StorylineMemoryService
    from chat_buddy.characters.domain import Storyline
    from chat_buddy.characters.ui.storyline_memory import render_storyline_memory

    render_storyline_memory(
        cast(StorylineMemoryService, service),
        cast(Storyline, storyline),
        cast(UUID, selected_leaf_id),
    )


@pytest.fixture
def memory_ui() -> tuple[Mock, Storyline, StorylineMemory, MemoryConflict]:
    """Provide one active Storyline with reinforced memory and a conflict.

    Returns:
        Service double, Storyline, memory, and targeted conflict.
    """

    storyline = _storyline()
    memory = _memory(storyline, reinforcement=True)
    conflict = _conflict(memory)
    service = Mock(spec=StorylineMemoryService)
    service.list_memories.return_value = (memory,)
    service.list_conflicts.return_value = (conflict,)
    return service, storyline, memory, conflict


def test_shows_current_lineage_reinforcement_and_extraction_provenance(
    memory_ui: tuple[Mock, Storyline, StorylineMemory, MemoryConflict],
) -> None:
    """Explain current state plus every durable source and strategy detail.

    Args:
        memory_ui:
            Focused memory-view fixture.
    """

    service, storyline, _, _ = memory_ui
    app = _app(service, storyline)

    assert not app.exception
    assert app.subheader[0].value == "Storyline memory"
    assert any(
        "Reinforced by 1 additional source turn" in row.value for row in app.caption
    )
    assert any("baseline.context 1.0.0" in row.value for row in app.caption)
    assert any("ollama/local-model" in row.value for row in app.caption)
    assert any("max_output_tokens=256" in row.value for row in app.caption)
    assert any("Current state: active" in row.value for row in app.caption)
    service.list_memories.assert_called_with(storyline.id)
    service.list_conflicts.assert_called_with(storyline.id)


def test_correction_rerenders_the_new_user_revision_immediately(
    memory_ui: tuple[Mock, Storyline, StorylineMemory, MemoryConflict],
) -> None:
    """Apply a guarded correction and expose its next-prompt value on rerun.

    Args:
        memory_ui:
            Focused memory-view fixture.
    """

    service, storyline, memory, _ = memory_ui
    corrected = _corrected(memory, "favorite drink", "The user prefers coffee.")

    def correct(command: CorrectMemoryCommand) -> StorylineMemory:
        """Expose committed content to the automatic rerun.

        Args:
            command:
                Submitted guarded correction.

        Returns:
            Updated memory lineage.
        """

        service.list_memories.return_value = (corrected,)
        return corrected

    service.correct.side_effect = correct
    app = _app(service, storyline)
    next(row for row in app.text_area if row.label == "Corrected memory").set_value(
        "The user prefers coffee."
    )
    next(
        button for button in app.button if button.label == "Save correction"
    ).click().run()

    command = service.correct.call_args.args[0]
    assert command.expected_revision_id == memory.current.id
    assert command.content == "The user prefers coffee."
    assert any(row.value == "The user prefers coffee." for row in app.markdown)
    assert any("authorship: user" in row.value for row in app.caption)


def test_exclusion_reactivation_and_stale_revision_are_guarded(
    memory_ui: tuple[Mock, Storyline, StorylineMemory, MemoryConflict],
) -> None:
    """Use observed revisions for both lifecycle directions and surface staleness.

    Args:
        memory_ui:
            Focused memory-view fixture.
    """

    service, storyline, memory, _ = memory_ui
    app = _app(service, storyline)
    next(
        button for button in app.button if button.label == "Exclude memory"
    ).click().run()
    excluded_command = cast(ChangeMemoryStateCommand, service.exclude.call_args.args[0])
    assert excluded_command.memory_id == memory.id
    assert excluded_command.expected_revision_id == memory.current.id

    excluded = _excluded(memory)
    service.list_memories.return_value = (excluded,)
    app = _app(service, storyline)
    service.reactivate.side_effect = StaleMemoryRevisionError("new revision")
    next(
        button for button in app.button if button.label == "Reactivate memory"
    ).click().run()
    reactivation = cast(ChangeMemoryStateCommand, service.reactivate.call_args.args[0])
    assert reactivation.expected_revision_id == excluded.current.id
    assert any("changed" in row.value for row in app.warning)


def test_permanent_deletion_requires_confirmation_and_complete_ownership(
    memory_ui: tuple[Mock, Storyline, StorylineMemory, MemoryConflict],
) -> None:
    """Keep hard deletion disabled until its explicit warning is accepted.

    Args:
        memory_ui:
            Focused memory-view fixture.
    """

    service, storyline, memory, _ = memory_ui
    app = _app(service, storyline)
    delete = next(
        button for button in app.button if button.label == "Permanently delete memory"
    )
    assert delete.disabled
    checkbox = next(
        row
        for row in app.checkbox
        if row.label.startswith("I understand this permanently deletes")
    )
    checkbox.check().run()
    next(
        button for button in app.button if button.label == "Permanently delete memory"
    ).click().run()

    command = cast(DeleteMemoryCommand, service.delete.call_args.args[0])
    assert command.continuity_id == storyline.id
    assert command.memory_id == memory.id
    assert command.expected_revision_id == memory.current.id


def test_conflict_separates_new_evidence_and_keeps_current_value(
    memory_ui: tuple[Mock, Storyline, StorylineMemory, MemoryConflict],
) -> None:
    """Inspect both interpretations and dismiss without mutating memory.

    Args:
        memory_ui:
            Focused memory-view fixture.
    """

    service, storyline, memory, conflict = memory_ui
    app = _app(service, storyline)

    assert any(row.value == "**New evidence proposes**" for row in app.markdown)
    assert any(row.value == "**Current memory**" for row in app.markdown)
    next(
        button for button in app.button if button.label == "Keep current value"
    ).click().run()
    command = cast(
        DismissMemoryConflictCommand, service.dismiss_conflict.call_args.args[0]
    )
    assert command.continuity_id == storyline.id
    assert command.conflict_id == conflict.id
    assert command.expected_revision_id == memory.current.id
    service.correct.assert_not_called()


def test_conflict_opens_normal_correction_for_the_exact_owned_revision(
    memory_ui: tuple[Mock, Storyline, StorylineMemory, MemoryConflict],
) -> None:
    """Open the normal correction form for the exact target revision.

    Args:
        memory_ui:
            Focused memory-view fixture.
    """

    _, storyline, memory, _ = memory_ui
    app = _app(memory_ui[0], storyline)
    next(
        button for button in app.button if button.label == "Correct current memory"
    ).click().run()
    target = app.session_state["characters_storyline_memory_correction_target"]
    assert target == (
        storyline.identity_id,
        storyline.persona_id,
        storyline.id,
        storyline.revision,
        SELECTED_LEAF_ID,
        memory.id,
        memory.current.id,
    )


def test_branch_change_invalidates_every_memory_widget_namespace(
    memory_ui: tuple[Mock, Storyline, StorylineMemory, MemoryConflict],
) -> None:
    """Give the same revision fresh widget state after branch selection changes.

    Args:
        memory_ui:
            Focused memory-view fixture.
    """

    service, storyline, _, _ = memory_ui
    first = _app(service, storyline)
    first_key = next(
        button.key for button in first.button if button.label == "Exclude memory"
    )
    second = _app(service, storyline, selected_leaf_id=uuid4())
    second_key = next(
        button.key for button in second.button if button.label == "Exclude memory"
    )

    assert first_key != second_key


def test_empty_and_archived_storylines_are_clear_and_read_only(
    memory_ui: tuple[Mock, Storyline, StorylineMemory, MemoryConflict],
) -> None:
    """Explain empty state and suppress all writes for archived continuity.

    Args:
        memory_ui:
            Focused memory-view fixture.
    """

    service, storyline, memory, conflict = memory_ui
    service.list_memories.return_value = ()
    service.list_conflicts.return_value = ()
    app = _app(service, storyline)
    assert any("No memories" in row.value for row in app.info)
    assert any("No unresolved" in row.value for row in app.info)

    archived = storyline.model_copy(update={"lifecycle": ContinuityLifecycle.ARCHIVED})
    service.list_memories.return_value = (memory,)
    service.list_conflicts.return_value = (conflict,)
    app = _app(service, archived)
    forbidden = {
        "Save correction",
        "Exclude memory",
        "Reactivate memory",
        "Permanently delete memory",
        "Keep current value",
        "Dismiss conflict",
    }
    assert not any(button.label in forbidden for button in app.button)
    assert any("read-only" in row.value for row in app.info)


def _app(
    service: Mock,
    storyline: Storyline,
    selected_leaf_id: UUID = SELECTED_LEAF_ID,
) -> AppTest:
    """Execute the isolated view with explicit serializable runner arguments.

    Args:
        service:
            Memory application-service double.
        storyline:
            Selected Storyline snapshot.
        selected_leaf_id:
            Selected branch checkpoint used to scope widget state.

    Returns:
        Executed Streamlit test application.
    """

    return AppTest.from_function(
        _render,
        args=(service, storyline, selected_leaf_id),
        default_timeout=10,
    ).run()


def _storyline() -> Storyline:
    """Create the fields consumed by the focused view.

    Returns:
        Active Storyline snapshot.
    """

    return Storyline.model_construct(
        id=uuid4(),
        identity_id=uuid4(),
        persona_id=uuid4(),
        name="Long Road",
        lifecycle=ContinuityLifecycle.ACTIVE,
        relationship=None,
        revision=3,
    )


def _memory(storyline: Storyline, *, reinforcement: bool) -> StorylineMemory:
    """Create one extracted logical memory.

    Args:
        storyline:
            Owning continuity.
        reinforcement:
            Whether a second supporting turn is present.

    Returns:
        Complete logical memory snapshot.
    """

    evidence = _evidence(storyline)
    memory_id = uuid4()
    revision = _revision(memory_id, evidence)
    evidence_rows = (evidence, _evidence(storyline)) if reinforcement else (evidence,)
    return StorylineMemory(
        id=memory_id,
        continuity_id=storyline.id,
        current_revision_id=revision.id,
        revisions=(revision,),
        evidence=evidence_rows,
    )


def _evidence(storyline: Storyline) -> MemoryEvidence:
    """Create exact source and extraction provenance.

    Args:
        storyline:
            Owning continuity.

    Returns:
        Valid evidence snapshot.
    """

    scene_id = uuid4()
    return MemoryEvidence(
        id=uuid4(),
        scope=ConversationScope(
            identity_id=storyline.identity_id,
            persona_id=storyline.persona_id,
            continuity_id=storyline.id,
            conversation_id=uuid4(),
        ),
        scene_id=scene_id,
        user_message_id=uuid4(),
        persona_message_id=uuid4(),
        persona_checkpoint=2,
        occurrence=ScenePosition(scene_id=scene_id, position=1),
        learned=ScenePosition(scene_id=scene_id, position=1),
        extraction=ExtractionProvenance(
            selector=StrategyIdentity(name="baseline.context", version="1.0.0"),
            extractor=StrategyIdentity(name="baseline.delta", version="1.0.0"),
            prompt_schema_version="1.0.0",
            provider="ollama",
            model="local-model",
            configuration=GenerationConfiguration(max_output_tokens=256),
        ),
        created_at=NOW,
    )


def _revision(memory_id: UUID, evidence: MemoryEvidence) -> MemoryRevision:
    """Create one initial extracted revision.

    Args:
        memory_id:
            Logical-memory identifier.
        evidence:
            Originating evidence.

    Returns:
        Valid active revision.
    """

    return MemoryRevision(
        id=uuid4(),
        memory_id=memory_id,
        continuity_id=evidence.scope.continuity_id,
        revision=1,
        predecessor_id=None,
        subject="favorite drink",
        content="The user prefers tea.",
        state=MemoryRevisionState.ACTIVE,
        authorship=MemoryAuthorship.EXTRACTED,
        kind=MemoryRevisionKind.EXTRACTION,
        source=evidence,
        created_at=NOW,
    )


def _corrected(memory: StorylineMemory, subject: str, content: str) -> StorylineMemory:
    """Append a user-authored correction snapshot.

    Args:
        memory:
            Existing active lineage.
        subject:
            Corrected subject.
        content:
            Corrected content.

    Returns:
        Updated complete lineage.
    """

    previous = memory.current.model_copy(
        update={"state": MemoryRevisionState.SUPERSEDED}
    )
    current = MemoryRevision(
        id=uuid4(),
        memory_id=memory.id,
        continuity_id=memory.continuity_id,
        revision=2,
        predecessor_id=previous.id,
        subject=subject,
        content=content,
        state=MemoryRevisionState.ACTIVE,
        authorship=MemoryAuthorship.USER,
        kind=MemoryRevisionKind.USER_CORRECTION,
        source=previous.source,
        created_at=NOW + timedelta(minutes=1),
    )
    return StorylineMemory(
        id=memory.id,
        continuity_id=memory.continuity_id,
        current_revision_id=current.id,
        revisions=(previous, current),
        evidence=memory.evidence,
    )


def _excluded(memory: StorylineMemory) -> StorylineMemory:
    """Append an excluded lifecycle revision.

    Args:
        memory:
            Existing active lineage.

    Returns:
        Updated excluded lineage.
    """

    previous = memory.current.model_copy(
        update={"state": MemoryRevisionState.SUPERSEDED}
    )
    current = previous.model_copy(
        update={
            "id": uuid4(),
            "revision": 2,
            "predecessor_id": previous.id,
            "state": MemoryRevisionState.EXCLUDED,
            "kind": MemoryRevisionKind.EXCLUSION,
            "created_at": NOW + timedelta(minutes=1),
        }
    )
    return StorylineMemory(
        id=memory.id,
        continuity_id=memory.continuity_id,
        current_revision_id=current.id,
        revisions=(previous, current),
        evidence=memory.evidence,
    )


def _conflict(memory: StorylineMemory) -> MemoryConflict:
    """Create an unresolved targeted conflict.

    Args:
        memory:
            Target logical memory.

    Returns:
        Valid unresolved conflict.
    """

    return MemoryConflict(
        id=uuid4(),
        continuity_id=memory.continuity_id,
        memory_id=memory.id,
        observed_revision_id=memory.current.id,
        proposed_subject=memory.current.subject,
        proposed_content="The user may prefer coffee.",
        evidence=_evidence(
            Storyline.model_construct(
                id=memory.continuity_id,
                identity_id=memory.current.source.scope.identity_id,
                persona_id=memory.current.source.scope.persona_id,
                lifecycle=ContinuityLifecycle.ACTIVE,
            )
        ),
        state=MemoryConflictState.UNRESOLVED,
        created_at=NOW,
        dismissed_at=None,
    )
