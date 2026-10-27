"""Durable bounded Characters generation with isolated turn recovery."""

import logging
from collections.abc import Generator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from chat_buddy.characters.application.branch_policy import (
    DeferredBranchModeFactsResolver,
    decide_branch_mode,
)
from chat_buddy.characters.application.context_service import (
    OngoingContextBudgeter,
    OngoingContextEligibility,
    StorylineContextBudgeter,
)
from chat_buddy.characters.application.rolling_summary_service import (
    RollingSummaryService,
)
from chat_buddy.characters.application.storyline_conversation import (
    StorylineConversationAdapter,
)
from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    AttemptConflictError,
    BranchDecision,
    BranchModeFactsResolver,
    ContextCapacityError,
    ContinuityMode,
    ContinuityRepository,
    ConversationGraphRepository,
    ConversationGraphView,
    ConversationHistory,
    ConversationRepository,
    ConversationScope,
    ConversationSettings,
    ConversationTarget,
    EffectiveGeneration,
    ForkRequiredError,
    GenerationAttempt,
    GraphAction,
    GraphActionRequest,
    GraphNodeView,
    IdentityRepository,
    IncompleteTurnError,
    ModelDescriptor,
    ModelRegistry,
    PersonaRepository,
    PromptMessage,
    ResponseMemorySelection,
    RetryAvailability,
    Scene,
    SelectedPath,
    Storyline,
    SubmittedInput,
    SummaryRepository,
    TokenCounter,
)


class _ConversationPersistence(
    ConversationRepository, ConversationGraphRepository, Protocol
):
    """Combined persistence capabilities required by conversation orchestration."""


class _StorylineExtractionProcessor(Protocol):
    """Post-completion Storyline extraction seam."""

    def process(
        self, target: ConversationTarget, source_persona_message_id: UUID
    ) -> object:
        """Process one committed Storyline response.

        Args:
            target:
                Exact Storyline scene target.
            source_persona_message_id:
                Newly committed persona response.

        Returns:
            Durable extraction outcome.
        """

        ...


class _StorylineResponseMemoryProvider(Protocol):
    """Read and select eligible memory for one Storyline response."""

    def select(
        self, storyline: Storyline, scene: Scene, counter: TokenCounter
    ) -> ResponseMemorySelection:
        """Return a bounded selection for an exact Storyline scene.

        Args:
            storyline:
                Owning Storyline snapshot.
            scene:
                Exact response scene.
            counter:
                Active provider token counter.

        Returns:
            Independently versioned response-memory selection.
        """

        ...


logger = logging.getLogger(__name__)


class ConversationService:
    """Orchestrate short repository operations around external streaming calls."""

    def __init__(
        self,
        conversations: _ConversationPersistence,
        continuities: ContinuityRepository,
        identities: IdentityRepository,
        personas: PersonaRepository,
        summaries: SummaryRepository,
        models: ModelRegistry,
        branch_mode_facts: BranchModeFactsResolver | None = None,
        storyline_adapter: StorylineConversationAdapter | None = None,
        memory_extraction: _StorylineExtractionProcessor | None = None,
        response_memories: _StorylineResponseMemoryProvider | None = None,
    ) -> None:
        """Bind Characters-owned contracts only.

        Args:
            conversations:
                Durable message and attempt repository.
            continuities:
                Ownership and starting-state reader.
            identities:
                Frozen identity reader.
            personas:
                Frozen persona reader.
            summaries:
                Owned rolling-summary persistence.
            models:
                Replaceable provider/model capabilities.
            branch_mode_facts:
                Optional future-mode fact adapter; unavailable facts fail closed.
            storyline_adapter:
                Optional exact Storyline scene ownership and policy adapter.
            memory_extraction:
                Optional post-completion Storyline memory workflow.
            response_memories:
                Optional branch-aware Storyline response-memory workflow.
        """

        self._conversations = conversations
        self._continuities = continuities
        self._identities = identities
        self._personas = personas
        self._models = models
        self._storyline_adapter = storyline_adapter
        self._memory_extraction = memory_extraction
        self._response_memories = response_memories
        self._branch_mode_facts = (
            branch_mode_facts or storyline_adapter or DeferredBranchModeFactsResolver()
        )
        self._eligibility = OngoingContextEligibility()
        self._budgeter = OngoingContextBudgeter()
        self._storyline_budgeter = StorylineContextBudgeter()
        self._summaries = RollingSummaryService(summaries, models)

    def response_models(self) -> tuple[ModelDescriptor, ...]:
        """List configured models supporting persona responses.

        Returns:
            Selectable response model descriptors.
        """

        return tuple(
            model
            for model in self._models.list_models()
            if "response" in model.capabilities
        )

    def default_settings(self) -> ConversationSettings:
        """Resolve the configured response default for a new conversation.

        Returns:
            Requested default selection.
        """

        generation = self._models.resolve_default("response")
        return ConversationSettings(
            provider=generation.model.provider, model=generation.model.model
        )

    def history(
        self, target: ConversationScope | ConversationTarget
    ) -> ConversationHistory:
        """Inspect committed history and incomplete output separately.

        Args:
            target:
                Legacy Ongoing scope or explicit mode-owned target.

        Returns:
            Detached durable history, including archives.
        """

        scope = self._scope(target)
        history = self._conversations.history(scope)
        if isinstance(target, ConversationTarget):
            self._validate_target(target, history, writable=False)
        return history

    def inspect_graph(
        self, target: ConversationScope | ConversationTarget
    ) -> ConversationGraphView:
        """Return a detached deterministic view of every saved future.

        Args:
            target:
                Legacy Ongoing scope or explicit mode-owned target.

        Returns:
            Graph nodes with alternatives, retry counts, selection, and current
            branch availability.
        """

        scope = self._scope(target)
        graph = self._conversations.graph(scope)
        history = self.history(target)
        if (
            isinstance(target, ConversationTarget)
            and target.mode == ContinuityMode.STORYLINE
        ):
            storyline, _ = self._validate_target(target, history, writable=False)
            if storyline is None:
                raise ValueError("Storyline target resolution failed")
            lifecycle = storyline.lifecycle
        else:
            continuity = self._continuities.get(
                scope.identity_id, scope.persona_id, scope.continuity_id
            )
            lifecycle = continuity.lifecycle
        selected_ids = {message.id for message in graph.selected_path().messages}
        alternatives_by_parent: dict[UUID, tuple[UUID, ...]] = {}
        for node in graph.nodes:
            if node.role != "persona" or node.parent_id is None:
                continue
            alternatives_by_parent.setdefault(node.parent_id, ())
            alternatives_by_parent[node.parent_id] += (node.id,)
        blocked = lifecycle != "active" or any(
            attempt.status in {"pending", "streaming"} for attempt in history.attempts
        )
        views = []
        for node in graph.nodes:
            alternatives = (
                alternatives_by_parent.get(node.parent_id, ())
                if node.role == "persona" and node.parent_id is not None
                else ()
            )
            selected_leaf = node.id == graph.selected_leaf_id
            views.append(
                GraphNodeView(
                    message=node,
                    alternative_ids=alternatives,
                    retry_count=max(len(alternatives) - 1, 0),
                    selected=node.id in selected_ids,
                    selected_leaf=selected_leaf,
                    branchable=(not blocked and node.role == "persona"),
                )
            )
        return ConversationGraphView(
            scope=scope,
            selected_leaf_id=graph.selected_leaf_id,
            nodes=tuple(views),
        )

    def select_alternative(
        self,
        target: ConversationScope | ConversationTarget,
        message_id: UUID,
        expected_selected_leaf_id: UUID,
    ) -> SelectedPath:
        """Select an exact off-path persona alternative or saved future leaf.

        Args:
            target:
                Legacy Ongoing scope or explicit mode-owned target.
            message_id:
                Exact alternative or saved descendant leaf.
            expected_selected_leaf_id:
                Last selected leaf observed by the caller.

        Returns:
            Newly selected root-to-leaf ancestry.
        """

        scope = self._scope(target)
        self._validate_write_target(target, self._conversations.history(scope))
        return self._conversations.apply_action(
            GraphActionRequest(
                scope=scope,
                action=GraphAction.ALTERNATIVE_SELECTION,
                expected_selected_leaf_id=expected_selected_leaf_id,
                target_message_id=message_id,
            )
        )

    def select_saved_future(
        self,
        target: ConversationScope | ConversationTarget,
        message_id: UUID,
        expected_selected_leaf_id: UUID,
    ) -> SelectedPath:
        """Restore one exact saved future leaf without guessing descendants.

        Args:
            target:
                Legacy Ongoing scope or explicit mode-owned target.
            message_id:
                Exact saved descendant leaf.
            expected_selected_leaf_id:
                Last selected leaf observed by the caller.

        Returns:
            Newly selected root-to-leaf ancestry.
        """

        return self.select_alternative(target, message_id, expected_selected_leaf_id)

    def branch_from_here(
        self,
        target: ConversationScope | ConversationTarget,
        message_id: UUID,
        expected_selected_leaf_id: UUID,
    ) -> SelectedPath:
        """Select any owned persona node as the next-send branch point.

        Args:
            target:
                Legacy Ongoing scope or explicit mode-owned target.
            message_id:
                Exact owned persona branch point.
            expected_selected_leaf_id:
                Last selected leaf observed by the caller.

        Returns:
            Selected branch-point ancestry without deleting any saved future.
        """

        scope = self._scope(target)
        history = self._conversations.history(scope)
        if isinstance(target, ConversationTarget):
            storyline, _ = self._validate_target(target, history, writable=False)
            if storyline is not None and storyline.lifecycle != "active":
                raise ArchivedContinuityError("Archived Storylines are read-only")
        self._authorize_mode_action(target, message_id)
        return self._conversations.apply_action(
            GraphActionRequest(
                scope=scope,
                action=GraphAction.BRANCH_FROM_HERE,
                expected_selected_leaf_id=expected_selected_leaf_id,
                target_message_id=message_id,
            )
        )

    def resume(
        self, target: ConversationScope | ConversationTarget
    ) -> ConversationHistory:
        """Reconcile attempts without progress for five minutes, then reload.

        Args:
            target:
                Legacy Ongoing scope or explicit mode-owned target.

        Returns:
            Saved history with expired attempts interrupted.
        """

        scope = self._scope(target)
        history = self._conversations.reconcile(
            scope, datetime.now(UTC) - timedelta(minutes=5)
        )
        if isinstance(target, ConversationTarget):
            self._validate_target(target, history, writable=False)
        return history

    def configure(
        self,
        target: ConversationScope | ConversationTarget,
        settings: ConversationSettings,
    ) -> None:
        """Validate and persist defaults affecting only future attempts.

        Args:
            target:
                Legacy Ongoing scope or explicit mode-owned target.
            settings:
                Requested provider, model, and overrides.
        """

        self._models.resolve(
            settings.provider, settings.model, "response", settings.requested
        )
        scope = self._scope(target)
        self._validate_write_target(target, self._conversations.history(scope))
        self._conversations.configure(scope, settings)

    def send(
        self,
        target: ConversationScope | ConversationTarget,
        submitted: SubmittedInput,
    ) -> GenerationAttempt:
        """Validate capacity before atomically committing input and a pending attempt.

        Args:
            target:
                Legacy Ongoing scope or explicit mode-owned target.
            submitted:
                Validated new input.

        Returns:
            Durable pending attempt to pass to stream.
        """

        return self._prepare(target, submitted)

    def continue_incomplete_turn(
        self, target: ConversationScope | ConversationTarget
    ) -> GenerationAttempt:
        """Reserve another attempt for the existing unmatched input.

        Args:
            target:
                Legacy Ongoing scope or explicit mode-owned target.

        Returns:
            New attempt preserving all prior attempt provenance.
        """

        return self._prepare(target, None)

    def retry_availability(
        self, target: ConversationScope | ConversationTarget
    ) -> RetryAvailability:
        """Return successful retry accounting for the selected final response.

        Args:
            target:
                Legacy Ongoing scope or explicit mode-owned target.

        Returns:
            Durable retry accounting for the selected turn.

        Raises:
            IncompleteTurnError:
                If no completed persona response is selected.
        """

        scope = self._scope(target)
        history = self.history(target)
        tail = history.messages[-1] if history.messages else None
        if tail is None or tail.role != "persona":
            raise IncompleteTurnError("No completed response is available to retry")
        return self._conversations.retry_availability(scope, tail.id)

    def retry_completed_response(
        self, target: ConversationScope | ConversationTarget
    ) -> GenerationAttempt:
        """Reserve a new attempt for the selected final persona response.

        Args:
            target:
                Legacy Ongoing scope or explicit mode-owned target.

        Returns:
            Durable pending retry attempt.
        """

        scope = self._scope(target)
        history = self.history(target)
        self._validate_write_target(target, history)
        if any(
            attempt.status in {"pending", "streaming"} for attempt in history.attempts
        ):
            raise AttemptConflictError("An attempt is already active")

        tail = history.messages[-1] if history.messages else None
        if tail is None or tail.role != "persona":
            raise IncompleteTurnError("No completed response is available to retry")

        if history.settings is None:
            generation = self._models.resolve_default("response")
            settings = ConversationSettings(
                provider=generation.model.provider, model=generation.model.model
            )
        else:
            settings = history.settings
            generation = self._models.resolve(
                settings.provider, settings.model, "response", settings.requested
            )
        retry_history = history.model_copy(update={"messages": history.messages[:-1]})
        self._prompt(
            target,
            retry_history,
            generation,
            None,
            retry_history.messages[-1].id,
        )
        return self._conversations.begin_retry(scope, generation, settings, tail.id)

    def branch_decision(
        self,
        target: ConversationScope | ConversationTarget,
        source_message_id: UUID,
    ) -> BranchDecision:
        """Resolve the mode disposition with exact source references.

        Args:
            target:
                Legacy Ongoing scope or explicit mode-owned target.
            source_message_id:
                Exact persona response governing the action.

        Returns:
            In-place or fork-required policy decision.
        """

        scope = self._scope(target)
        self.history(target)
        mode = (
            target.mode
            if isinstance(target, ConversationTarget)
            else self._continuities.get(
                scope.identity_id, scope.persona_id, scope.continuity_id
            ).mode
        )
        return self._branch_decision(scope, source_message_id, mode)

    def stream(
        self, target: ConversationScope | ConversationTarget, attempt_id: UUID
    ) -> Generator[str, None, None]:
        """Stream durable chunks, then atomically commit the completed response.

        The caller must exhaust or close this iterator. Unconsumed pending attempts
        and crashes are reconciled after their heartbeat expires.

        Args:
            target:
                Legacy Ongoing scope or explicit mode-owned target.
            attempt_id:
                Pending attempt returned by send or continuation.

        Yields:
            Text already persisted as separate attempt output.
        """

        # A losing duplicate consumer must never stop the winning stream.
        scope = self._scope(target)
        self._validate_write_target(target, self._conversations.history(scope))
        attempt = self._conversations.claim(scope, attempt_id)
        output: Iterator[str] | None = None
        completed = False
        try:
            history = self.history(target)
            summary_path_leaf_id: UUID | None = None
            if (
                history.messages
                and history.messages[-1].role == "persona"
                and len(history.messages) >= 2
                and history.messages[-2].id == attempt.user_message_id
            ):
                summary_path_leaf_id = attempt.user_message_id
                history = history.model_copy(update={"messages": history.messages[:-1]})

            prompt = self._prompt(
                target,
                history,
                attempt.generation,
                None,
                summary_path_leaf_id,
            )
            gateway = self._models.response_gateway(attempt.generation.model.provider)
            output = gateway.stream(prompt, attempt.generation)
            for chunk in output:
                self._conversations.append(scope, attempt_id, chunk)
                yield chunk
            message = self._conversations.complete(scope, attempt_id)
            completed = True
            if (
                self._memory_extraction is not None
                and isinstance(target, ConversationTarget)
                and target.mode == ContinuityMode.STORYLINE
            ):
                try:
                    self._memory_extraction.process(target, message.id)
                except Exception:
                    logger.exception(
                        "Storyline memory extraction did not reach a terminal "
                        "outcome for persona message %s.",
                        message.id,
                    )
        except Exception:
            self._conversations.stop(scope, attempt_id, "failed")
            raise
        finally:
            try:
                close = getattr(output, "close", None)
                if close is not None:
                    close()
            finally:
                if not completed:
                    self._conversations.stop(scope, attempt_id, "interrupted")

    def _prepare(
        self,
        target: ConversationScope | ConversationTarget,
        submitted: SubmittedInput | None,
    ) -> GenerationAttempt:
        """Preflight an isolated prompt and fence any concurrent history change.

        Args:
            target:
                Legacy Ongoing scope or explicit mode-owned target.
            submitted:
                New input or incomplete-turn continuation.

        Returns:
            Atomically reserved pending attempt.

        Raises:
            AttemptConflictError:
                If another attempt is active.
            IncompleteTurnError:
                If the requested action does not match the saved tail.
        """

        scope = self._scope(target)
        history = self.history(target)
        self._validate_write_target(target, history)
        if any(
            attempt.status in {"pending", "streaming"} for attempt in history.attempts
        ):
            raise AttemptConflictError("An attempt is already active")

        tail = history.messages[-1] if history.messages else None
        unmatched = tail is not None and tail.role == "user"
        if submitted is not None and unmatched:
            raise IncompleteTurnError("Continue the existing unmatched input")
        if submitted is None and not unmatched:
            raise IncompleteTurnError("No incomplete turn exists")

        if history.settings is None:
            generation = self._models.resolve_default("response")
            settings = ConversationSettings(
                provider=generation.model.provider, model=generation.model.model
            )
        else:
            settings = history.settings
            generation = self._models.resolve(
                settings.provider, settings.model, "response", settings.requested
            )

        self._prompt(
            target, history, generation, submitted.content if submitted else None
        )
        expected_selected_leaf_id = tail.id if tail is not None else None

        return self._conversations.begin(
            scope,
            generation,
            settings,
            expected_selected_leaf_id,
            submitted,
        )

    def _branch_decision(
        self,
        scope: ConversationScope,
        source_message_id: UUID,
        mode: ContinuityMode,
    ) -> BranchDecision:
        """Resolve and validate adapter facts before applying pure policy.

        Args:
            scope:
                Exact source conversation references.
            source_message_id:
                Exact persona response governing the action.
            mode:
                Persisted continuity mode.

        Returns:
            Fail-closed policy decision.
        """

        facts = self._branch_mode_facts.resolve(scope, source_message_id, mode)
        if (
            facts.scope != scope
            or facts.source_message_id != source_message_id
            or facts.mode != mode
        ):
            return BranchDecision(
                disposition="fork_required",
                scope=scope,
                source_message_id=source_message_id,
                reason="missing_or_contradictory_mode_facts",
            )
        return decide_branch_mode(facts)

    def _authorize_mode_action(
        self,
        target: ConversationScope | ConversationTarget,
        source_message_id: UUID,
    ) -> BranchDecision:
        """Require an in-place policy result before graph mutation.

        Args:
            target:
                Legacy Ongoing scope or explicit mode-owned target.
            source_message_id:
                Exact persona response governing the action.

        Returns:
            Authorized in-place decision.

        Raises:
            ForkRequiredError:
                If facts are missing, contradictory, or require a future fork.
        """

        decision = self.branch_decision(target, source_message_id)
        if decision.disposition == "fork_required":
            raise ForkRequiredError(decision)
        return decision

    def _prompt(
        self,
        target: ConversationScope | ConversationTarget,
        history: ConversationHistory,
        generation: EffectiveGeneration,
        current_input: str | None,
        summary_path_leaf_id: UUID | None = None,
    ) -> tuple[PromptMessage, ...]:
        """Assemble required blocks and reject full-history overflow deterministically.

        Args:
            target:
                Verified legacy Ongoing scope or mode-owned target.
            history:
                Scoped committed messages, never partial attempt output.
            generation:
                Immutable output-reserved budget.
            current_input:
                New input, absent for continuation.
            summary_path_leaf_id:
                Exact ancestry leaf used for compatible summary lookup.

        Returns:
            Bounded ordered prompt.

        Raises:
            ArchivedContinuityError:
                If the continuity is archived.
            ContextCapacityError:
                If all required context cannot fit.
        """

        scope = self._scope(target)
        persona = self._personas.get(scope.persona_id)
        identity = self._identities.get(scope.identity_id)
        counter = self._models.token_counter(generation.model.provider)
        current = self._summaries.current(scope, summary_path_leaf_id)
        storyline: Storyline | None = None
        scene: Scene | None = None
        continuity = None
        if isinstance(target, ConversationTarget):
            if target.mode == ContinuityMode.STORYLINE:
                storyline, scene = self._validate_target(target, history, writable=True)
                if storyline is None or scene is None:
                    raise ValueError("Storyline target resolution failed")
            else:
                continuity = self._continuities.get(
                    scope.identity_id, scope.persona_id, scope.continuity_id
                )
                if target.mode != continuity.mode:
                    raise ValueError(
                        "Conversation target mode does not match ownership"
                    )
        else:
            continuity = self._continuities.get(
                scope.identity_id, scope.persona_id, scope.continuity_id
            )
            if continuity.mode != ContinuityMode.ONGOING:
                raise ValueError("Storyline conversations require a mode-owned target")
        if continuity is not None and continuity.lifecycle != "active":
            raise ArchivedContinuityError("Archived continuity is read-only")

        for _ in range(len(history.messages) // 2 + 1):
            eligible = self._eligibility.select(history, current, current_input)
            if storyline is not None and scene is not None:
                memories = (
                    self._response_memories.select(
                        storyline, scene, counter
                    ).included_memories
                    if self._response_memories is not None
                    else ()
                )
                selection = self._storyline_budgeter.assemble(
                    persona,
                    identity,
                    storyline,
                    scene,
                    eligible,
                    generation,
                    counter,
                    memories,
                )
            else:
                if continuity is None:
                    raise ValueError("Ongoing target resolution failed")
                selection = self._budgeter.assemble(
                    persona, identity, continuity, eligible, generation, counter
                )
            if not selection.omitted_turns:
                return selection.prompt
            current = self._summaries.advance(
                scope,
                current,
                selection.omitted_turns,
                history.messages,
            )
        raise ContextCapacityError(
            "Conversation summary did not make bounded progress."
        )

    @staticmethod
    def _scope(target: ConversationScope | ConversationTarget) -> ConversationScope:
        """Normalize a legacy Ongoing scope or explicit mode-owned target.

        Args:
            target:
                Conversation operation target.

        Returns:
            Complete persistence ownership scope.
        """

        return target.scope if isinstance(target, ConversationTarget) else target

    def _validate_target(
        self,
        target: ConversationTarget,
        history: ConversationHistory,
        writable: bool,
    ) -> tuple[Storyline | None, Scene | None]:
        """Validate explicit mode ownership and optionally write policy.

        Args:
            target:
                Explicit mode-owned conversation target.
            history:
                Selected committed history.
            writable:
                Whether active latest-scene policy is required.

        Returns:
            Storyline and scene snapshots for Storyline targets, otherwise Nones.

        Raises:
            ValueError:
                If no Storyline adapter is configured for a Storyline target.
        """

        if target.mode == ContinuityMode.ONGOING:
            continuity = self._continuities.get(
                target.scope.identity_id,
                target.scope.persona_id,
                target.scope.continuity_id,
            )
            if continuity.mode != ContinuityMode.ONGOING:
                raise ValueError("Conversation target mode does not match ownership")
            return None, None
        if self._storyline_adapter is None:
            raise ValueError("Storyline conversation support is not configured")
        if writable:
            return self._storyline_adapter.require_writable(target, history)
        return self._storyline_adapter.inspect(target, history)

    def _validate_write_target(
        self,
        target: ConversationScope | ConversationTarget,
        history: ConversationHistory,
    ) -> None:
        """Apply mode-specific write authorization before reserving work.

        Args:
            target:
                Legacy Ongoing scope or explicit mode-owned target.
            history:
                Current selected history.
        """

        if isinstance(target, ConversationTarget):
            self._validate_target(target, history, writable=True)
