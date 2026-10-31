"""End-to-end acceptance of Stage 6 Storylines and contextual memory."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import (
    BaselineMemoryContextSelector,
    BaselineResponseMemorySelector,
    ConversationService,
    StorylineConversationAdapter,
    StorylineExtractionContextService,
    StorylineForkService,
    StorylineMemoryEligibility,
    StorylineMemoryExtractionService,
    StorylineMemoryService,
    StorylineResponseMemoryService,
    StorylineService,
)
from chat_buddy.characters.domain import (
    ActiveStorylineError,
    ChangeMemoryStateCommand,
    CorrectMemoryCommand,
    CreateMemoryCommand,
    DismissMemoryConflictCommand,
    ExtractionBudget,
    ExtractionProvenance,
    GenerationConfiguration,
    IncompleteLatestSceneError,
    MemoryDelta,
    MemoryDeltaCommand,
    MemoryEvidence,
    MemorySelectionResult,
    ModelDescriptor,
    NoMemoryChangeCommand,
    RecordMemoryConflictCommand,
    ReinforceMemoryCommand,
    ResponseMemoryBudget,
    StrategyIdentity,
    SubmittedInput,
    SupersedeMemoryCommand,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbConversationRepository,
    DbIdentityRepository,
    DbMemoryExtractionRepository,
    DbPersonaRepository,
    DbSceneRepository,
    DbStorylineForkRepository,
    DbStorylineMemoryRepository,
    DbStorylineRepository,
    DbSummaryRepository,
)
from chat_buddy.characters.infrastructure.llm import ConfiguredModelRegistry
from tests.characters_support import FakeResponse
from tests.integration.characters.test_ongoing_summary_context import (
    FakeSummary,
    MessageCountCounter,
)
from tests.integration.characters.test_storyline_conversations import _target
from tests.integration.characters.test_storyline_repositories import (
    _next_scene,
    _repositories_and_request,
)


class ScriptedDeltaExtractor:
    """Capture exact snapshots and emit a reviewed sequence of typed deltas."""

    _STRATEGY_ID = StrategyIdentity(name="acceptance.scripted_delta", version="1.0.0")

    def __init__(self, operations: tuple[str, ...]) -> None:
        """Store the expected operation sequence.

        Args:
            operations:
                Delta operation emitted for each completed response.
        """

        self._operations = list(operations)
        self.selections: list[MemorySelectionResult] = []
        self.deltas: list[MemoryDelta] = []

    @property
    def strategy_id(self) -> StrategyIdentity:
        """Return the stable acceptance extractor identity.

        Returns:
            Versioned strategy identity.
        """

        return self._STRATEGY_ID

    def extract(self, selection: MemorySelectionResult) -> MemoryDelta:
        """Emit the next delta using only opaque values in the supplied snapshot.

        Args:
            selection:
                Exact immutable contextual selection.

        Returns:
            One typed delta for the configured operation.
        """

        operation = self._operations.pop(0)
        self.selections.append(selection)
        provenance = self.provenance(selection)
        evidence = MemoryEvidence(
            id=uuid4(),
            scope=selection.context.scope,
            scene_id=selection.context.scene.scene_id,
            user_message_id=selection.context.source_turn.user.id,
            persona_message_id=selection.context.source_turn.persona.id,
            persona_checkpoint=selection.context.source_turn.persona.sequence,
            occurrence=selection.context.scene,
            learned=selection.context.scene,
            extraction=provenance,
            created_at=datetime.now(UTC),
        )
        memories = selection.context.eligible_memories
        command: MemoryDeltaCommand
        if operation == "create":
            command = CreateMemoryCommand(
                subject="departure drink",
                content="The traveler drinks jasmine tea before departure.",
                occurrence=selection.context.scene,
                evidence=evidence,
            )
        elif operation == "create_future":
            occurrence = memories[0].current.source.occurrence
            command = CreateMemoryCommand(
                subject="future reunion",
                content="The travelers plan a reunion after the journey.",
                occurrence=occurrence,
                evidence=evidence.model_copy(update={"occurrence": occurrence}),
            )
        elif operation == "reinforce":
            target = memories[0]
            command = ReinforceMemoryCommand(
                target_memory_id=target.id,
                expected_revision_id=target.current.id,
                content=target.current.content,
                evidence=evidence,
            )
        elif operation == "supersede":
            target = memories[0]
            command = SupersedeMemoryCommand(
                target_memory_id=target.id,
                expected_revision_id=target.current.id,
                subject=target.current.subject,
                content="The traveler now drinks oolong tea before departure.",
                occurrence=selection.context.scene,
                evidence=evidence,
            )
        elif operation == "conflict":
            target = memories[0]
            command = RecordMemoryConflictCommand(
                target_memory_id=target.id,
                expected_revision_id=target.current.id,
                subject=target.current.subject,
                content="The traveler may still prefer jasmine tea.",
                occurrence=selection.context.scene,
                evidence=evidence,
            )
        else:
            command = NoMemoryChangeCommand()
        delta = MemoryDelta(
            selection_id=selection.id,
            scope=selection.context.scope,
            source_persona_message_id=selection.context.source_turn.persona.id,
            extractor=self.strategy_id,
            commands=(command,),
        )
        self.deltas.append(delta)
        return delta

    def provenance(self, selection: MemorySelectionResult) -> ExtractionProvenance:
        """Describe the deterministic extraction configuration.

        Args:
            selection:
                Selection whose selector identity is retained.

        Returns:
            Complete extraction provenance.
        """

        return ExtractionProvenance(
            selector=selection.selector,
            extractor=self.strategy_id,
            prompt_schema_version="1.0.0",
            provider="acceptance",
            model="scripted-delta",
            configuration=GenerationConfiguration(max_output_tokens=128),
        )


def test_stage_six_milestone(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Prove Storyline, temporal-memory, fork, and restart behavior end to end.

    Args:
        characters_session_factory:
            Isolated Characters database sessions.
    """

    prove_stage_six_milestone(characters_session_factory)


def prove_stage_six_milestone(factory: sessionmaker[Session]) -> None:
    """Exercise the complete Stage 6 milestone through public services.

    Args:
        factory:
            SQLite or disposable PostgreSQL Characters sessions.
    """

    storylines, scenes, request = _repositories_and_request(factory)
    lifecycle = StorylineService(storylines, scenes, DbConversationRepository(factory))

    archived_storyline, _ = lifecycle.start(request)
    archived_storyline = lifecycle.archive(
        archived_storyline.identity_id,
        archived_storyline.persona_id,
        archived_storyline.id,
        archived_storyline.revision,
    )
    replacement_request = request.model_copy(
        update={"request_id": uuid4(), "name": "Independent return"}
    )
    storyline, first_scene = lifecycle.start(replacement_request)
    assert storyline.id != archived_storyline.id
    assert storyline.relationship == archived_storyline.relationship
    with pytest.raises(ActiveStorylineError):
        lifecycle.start(replacement_request.model_copy(update={"request_id": uuid4()}))

    responses = FakeResponse()
    summaries = FakeSummary()
    extractor = ScriptedDeltaExtractor(
        (
            "create",
            "reinforce",
            "conflict",
            "supersede",
            "no_change",
            "create_future",
            "no_change",
        )
    )
    app = _acceptance_service(
        factory, responses, summaries, extractor, storylines, scenes
    )
    first_target = _target(first_scene.id, first_scene.scope)

    source_responses: list[UUID] = []
    for user_text, response_text in (
        ("I drink jasmine tea before departure.", "I will remember jasmine tea."),
        ("Yes, jasmine tea before departure.", "That confirms the tea."),
        ("I might still prefer jasmine.", "That account is uncertain."),
    ):
        responses.chunks = (response_text,)
        attempt = app.send(first_target, SubmittedInput(content=user_text))
        list(app.stream(first_target, attempt.id))
        source_responses.append(app.history(first_target).messages[-1].id)

    summary = DbSummaryRepository(factory).get_current(first_scene.scope)
    assert summary is not None
    assert summaries.captured
    memory_repository = DbStorylineMemoryRepository(factory)
    memory = memory_repository.list(storyline.id)[0]
    assert tuple(delta.commands[0].operation for delta in extractor.deltas) == (
        "create",
        "reinforce",
        "conflict",
    )
    assert tuple(
        selection.context.source_turn.persona.id for selection in extractor.selections
    ) == tuple(source_responses)
    assert extractor.selections[0].included_memory_ids == ()
    assert extractor.selections[1].included_memory_ids == (memory.id,)
    assert extractor.selections[2].included_memory_ids == (memory.id,)
    assert all(
        "[new evidence:" in selection.prompt[-1] for selection in extractor.selections
    )

    conflicts = DbMemoryExtractionRepository(factory).list_conflicts(storyline.id)
    assert len(conflicts) == 1
    memory_service = StorylineMemoryService(
        memory_repository, DbMemoryExtractionRepository(factory)
    )
    memory_service.dismiss_conflict(
        DismissMemoryConflictCommand(
            continuity_id=storyline.id,
            conflict_id=conflicts[0].id,
            expected_revision_id=memory.current.id,
        )
    )

    responses.chunks = ("I will remember the change.",)
    changed_attempt = app.send(
        first_target, SubmittedInput(content="I changed to oolong tea.")
    )
    list(app.stream(first_target, changed_attempt.id))
    source_responses.append(app.history(first_target).messages[-1].id)
    assert extractor.deltas[-1].commands[0].operation == "supersede"

    responses.chunks = ("The alternate also remembers the change.",)
    retry = app.retry_completed_response(first_target)
    list(app.stream(first_target, retry.id))
    alternative_id = app.history(first_target).messages[-1].id
    conflict_selection = extractor.selections[-1]
    assert conflict_selection.context.source_turn.persona.id == alternative_id
    assert conflict_selection.included_memory_ids == ()
    assert extractor.deltas[-1].commands[0].operation == "no_change"

    selected = app.select_alternative(
        first_target, source_responses[-1], alternative_id
    )
    assert selected.selected_leaf_id == source_responses[-1]
    eligibility = lifecycle.append_eligibility(
        storyline.identity_id, storyline.persona_id, storyline.id
    )
    sequence = lifecycle.append_next(_next_scene(), eligibility)
    second_scene = sequence.scenes[-1]
    with pytest.raises(IncompleteLatestSceneError):
        lifecycle.append_next(
            _next_scene(),
            lifecycle.append_eligibility(
                storyline.identity_id, storyline.persona_id, storyline.id
            ),
        )

    second_target = _target(second_scene.id, second_scene.scope)
    responses.chunks = ("The corrected preference is available here.",)
    second_attempt = app.send(
        second_target, SubmittedInput(content="What do I drink before departure?")
    )
    list(app.stream(second_target, second_attempt.id))
    second_prompt = "\n".join(message.content for message in responses.captured[-1])
    assert "oolong tea" in second_prompt
    assert "jasmine account is uncertain" not in second_prompt
    assert "First-scene" not in second_prompt
    future_memory = next(
        candidate
        for candidate in memory_repository.list(storyline.id)
        if candidate.id != memory.id
    )
    assert future_memory.current.source.occurrence.position == 1
    assert future_memory.current.source.learned.position == 2

    current = memory_service.inspect_memory(storyline.id, memory.id)
    corrected = memory_service.correct(
        CorrectMemoryCommand(
            continuity_id=storyline.id,
            memory_id=memory.id,
            expected_revision_id=current.current.id,
            subject=current.current.subject,
            content="The traveler drinks roasted oolong tea before departure.",
        )
    )
    excluded = memory_service.exclude(
        ChangeMemoryStateCommand(
            operation="exclude",
            continuity_id=storyline.id,
            memory_id=memory.id,
            expected_revision_id=corrected.current.id,
        )
    )
    reactivated = memory_service.reactivate(
        ChangeMemoryStateCommand(
            operation="reactivate",
            continuity_id=storyline.id,
            memory_id=memory.id,
            expected_revision_id=excluded.current.id,
        )
    )
    assert reactivated.current.state == "active"

    responses.chunks = ("Roasted oolong is in the current context.",)
    corrected_attempt = app.send(
        second_target, SubmittedInput(content="Check the corrected memory.")
    )
    list(app.stream(second_target, corrected_attempt.id))
    corrected_prompt = "\n".join(message.content for message in responses.captured[-1])
    assert "roasted oolong tea" in corrected_prompt
    assert "jasmine tea before departure" not in corrected_prompt

    contexts = _context_service(factory, storylines, scenes)
    first_as_of = contexts.build(
        first_target,
        source_responses[-1],
        ExtractionBudget(input_tokens=1024, fixed_overhead_tokens=32),
    )
    assert first_as_of.included_memory_ids == (memory.id,)
    assert future_memory.id not in (
        *first_as_of.included_memory_ids,
        *first_as_of.omitted_memory_ids,
    )
    assert extractor.selections[-1].context.scene.position == 2
    assert set(extractor.selections[-1].included_memory_ids) == {
        memory.id,
        future_memory.id,
    }

    identities = DbIdentityRepository(factory)
    personas = DbPersonaRepository(factory)
    duplicate = identities.create(identities.get(storyline.identity_id).details)
    forks = StorylineForkService(
        storylines,
        scenes,
        DbConversationRepository(factory),
        DbConversationRepository(factory),
        identities,
        personas,
        DbStorylineForkRepository(factory),
    )
    current_storyline = storylines.get(
        storyline.identity_id, storyline.persona_id, storyline.id
    )
    preview = forks.preview(
        request_id=uuid4(),
        name="Roasted oolong fork",
        target=first_target,
        branch_point_message_id=source_responses[-1],
        expected_selected_leaf_id=source_responses[-1],
        expected_storyline_revision=current_storyline.revision,
        target_identity_id=duplicate.id,
        target_persona_id=storyline.persona_id,
    )
    fork = forks.confirm(preview)
    assert fork.storyline.identity_id == duplicate.id
    assert (
        identities.get(duplicate.id).details
        == identities.get(storyline.identity_id).details
    )
    assert fork.storyline.persona_id == storyline.persona_id
    assert len(fork.scenes) == 1
    assert memory_repository.list(fork.storyline.id)[0].id != memory.id

    restarted = _acceptance_service(
        factory,
        FakeResponse(),
        FakeSummary(),
        ScriptedDeltaExtractor(("no_change",)),
        DbStorylineRepository(factory),
        DbSceneRepository(factory),
    )
    assert restarted.resume(second_target).messages[-1].content == (
        "Roasted oolong is in the current context."
    )
    fork_target = _target(fork.scenes[0].id, fork.scenes[0].scope)
    assert restarted.resume(fork_target).messages[-1].content == (
        "I will remember the change."
    )
    assert (
        storylines.get(
            storyline.identity_id, storyline.persona_id, storyline.id
        ).lifecycle
        == "active"
    )
    assert (
        storylines.get(
            fork.storyline.identity_id, fork.storyline.persona_id, fork.storyline.id
        ).lifecycle
        == "active"
    )


def _acceptance_service(
    factory: sessionmaker[Session],
    responses: FakeResponse,
    summaries: FakeSummary,
    extractor: ScriptedDeltaExtractor,
    storylines: DbStorylineRepository,
    scenes: DbSceneRepository,
) -> ConversationService:
    """Compose the complete Stage 6 conversation path with test providers.

    Args:
        factory:
            Isolated Characters sessions.
        responses:
            Capturing response provider.
        summaries:
            Capturing summary provider.
        extractor:
            Capturing structured-delta strategy.
        storylines:
            Storyline ownership repository.
        scenes:
            Ordered scene repository.

    Returns:
        Fully composed Storyline conversation service.
    """

    counter = MessageCountCounter()
    models = (
        ModelDescriptor(
            provider="fake",
            model="response",
            context_tokens=190,
            output_tokens=10,
            capabilities=frozenset({"response"}),
        ),
        ModelDescriptor(
            provider="fake",
            model="summary",
            context_tokens=170,
            output_tokens=10,
            capabilities=frozenset({"summary"}),
        ),
    )
    registry = ConfiguredModelRegistry(
        models=models,
        responses={"fake": responses},
        summaries={"fake": summaries},
        counters={"fake": counter},
        defaults={"response": ("fake", "response"), "summary": ("fake", "summary")},
    )
    conversations = DbConversationRepository(factory)
    memories = DbStorylineMemoryRepository(factory)
    contexts = _context_service(factory, storylines, scenes, counter)
    extraction = StorylineMemoryExtractionService(
        contexts,
        extractor,
        memories,
        DbMemoryExtractionRepository(factory),
        ExtractionBudget(input_tokens=1024, fixed_overhead_tokens=32),
    )
    return ConversationService(
        conversations,
        DbContinuityRepository(factory),
        DbIdentityRepository(factory),
        DbPersonaRepository(factory),
        DbSummaryRepository(factory),
        registry,
        storyline_adapter=StorylineConversationAdapter(storylines, scenes),
        memory_extraction=extraction,
        response_memories=StorylineResponseMemoryService(
            scenes,
            conversations,
            memories,
            BaselineResponseMemorySelector(),
            ResponseMemoryBudget(input_tokens=1024),
        ),
    )


def _context_service(
    factory: sessionmaker[Session],
    storylines: DbStorylineRepository,
    scenes: DbSceneRepository,
    counter: MessageCountCounter | None = None,
) -> StorylineExtractionContextService:
    """Compose the real branch- and time-aware extraction snapshot builder.

    Args:
        factory:
            Isolated Characters sessions.
        storylines:
            Storyline ownership repository.
        scenes:
            Ordered scene repository.
        counter:
            Optional deterministic token counter.

    Returns:
        Complete extraction-context service.
    """

    return StorylineExtractionContextService(
        DbIdentityRepository(factory),
        DbPersonaRepository(factory),
        storylines,
        scenes,
        DbConversationRepository(factory),
        DbSummaryRepository(factory),
        DbStorylineMemoryRepository(factory),
        StorylineMemoryEligibility(),
        BaselineMemoryContextSelector(counter or MessageCountCounter()),
    )
