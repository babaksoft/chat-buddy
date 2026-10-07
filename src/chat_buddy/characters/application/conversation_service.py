"""Durable bounded Ongoing generation with isolated incomplete-turn recovery."""

from collections.abc import Generator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from chat_buddy.characters.application.context_service import (
    OngoingContextBudgeter,
    OngoingContextEligibility,
)
from chat_buddy.characters.application.rolling_summary_service import (
    RollingSummaryService,
)
from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    AttemptConflictError,
    ContextCapacityError,
    ContinuityRepository,
    ConversationGraphRepository,
    ConversationGraphView,
    ConversationHistory,
    ConversationRepository,
    ConversationScope,
    ConversationSettings,
    EffectiveGeneration,
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
    RetryAvailability,
    SelectedPath,
    SubmittedInput,
    SummaryRepository,
)


class _ConversationPersistence(
    ConversationRepository, ConversationGraphRepository, Protocol
):
    """Combined persistence capabilities required by Ongoing orchestration."""


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
        """

        self._conversations = conversations
        self._continuities = continuities
        self._identities = identities
        self._personas = personas
        self._models = models
        self._eligibility = OngoingContextEligibility()
        self._budgeter = OngoingContextBudgeter()
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

    def history(self, scope: ConversationScope) -> ConversationHistory:
        """Inspect committed history and incomplete output separately.

        Args:
            scope:
                Complete required ownership.

        Returns:
            Detached durable history, including archives.
        """

        return self._conversations.history(scope)

    def inspect_graph(self, scope: ConversationScope) -> ConversationGraphView:
        """Return a detached deterministic view of every saved future.

        Args:
            scope:
                Complete required ownership.

        Returns:
            Graph nodes with alternatives, retry counts, selection, and current
            branch availability.
        """

        graph = self._conversations.graph(scope)
        history = self._conversations.history(scope)
        continuity = self._continuities.get(
            scope.identity_id, scope.persona_id, scope.continuity_id
        )
        selected_ids = {message.id for message in graph.selected_path().messages}
        alternatives_by_parent: dict[UUID, tuple[UUID, ...]] = {}
        for node in graph.nodes:
            if node.role != "persona" or node.parent_id is None:
                continue
            alternatives_by_parent.setdefault(node.parent_id, ())
            alternatives_by_parent[node.parent_id] += (node.id,)
        blocked = continuity.lifecycle != "active" or any(
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
                    branchable=(
                        not blocked
                        and node.role == "persona"
                        and node.id in selected_ids
                        and not selected_leaf
                    ),
                )
            )
        return ConversationGraphView(
            scope=scope,
            selected_leaf_id=graph.selected_leaf_id,
            nodes=tuple(views),
        )

    def select_alternative(
        self,
        scope: ConversationScope,
        message_id: UUID,
        expected_selected_leaf_id: UUID,
    ) -> SelectedPath:
        """Select an exact off-path persona alternative or saved future leaf.

        Args:
            scope:
                Complete required ownership.
            message_id:
                Exact alternative or saved descendant leaf.
            expected_selected_leaf_id:
                Last selected leaf observed by the caller.

        Returns:
            Newly selected root-to-leaf ancestry.
        """

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
        scope: ConversationScope,
        message_id: UUID,
        expected_selected_leaf_id: UUID,
    ) -> SelectedPath:
        """Restore one exact saved future leaf without guessing descendants.

        Args:
            scope:
                Complete required ownership.
            message_id:
                Exact saved descendant leaf.
            expected_selected_leaf_id:
                Last selected leaf observed by the caller.

        Returns:
            Newly selected root-to-leaf ancestry.
        """

        return self.select_alternative(scope, message_id, expected_selected_leaf_id)

    def branch_from_here(
        self,
        scope: ConversationScope,
        message_id: UUID,
        expected_selected_leaf_id: UUID,
    ) -> SelectedPath:
        """Select an older persona node on the current path for the next send.

        Args:
            scope:
                Complete required ownership.
            message_id:
                Exact older selected-path persona node.
            expected_selected_leaf_id:
                Last selected leaf observed by the caller.

        Returns:
            Truncated selected ancestry without deleting its prior future.
        """

        return self._conversations.apply_action(
            GraphActionRequest(
                scope=scope,
                action=GraphAction.BRANCH_FROM_HERE,
                expected_selected_leaf_id=expected_selected_leaf_id,
                target_message_id=message_id,
            )
        )

    def resume(self, scope: ConversationScope) -> ConversationHistory:
        """Reconcile attempts without progress for five minutes, then reload.

        Args:
            scope:
                Complete required ownership.

        Returns:
            Saved history with expired attempts interrupted.
        """

        return self._conversations.reconcile(
            scope, datetime.now(UTC) - timedelta(minutes=5)
        )

    def configure(
        self, scope: ConversationScope, settings: ConversationSettings
    ) -> None:
        """Validate and persist defaults affecting only future attempts.

        Args:
            scope:
                Complete required ownership.
            settings:
                Requested provider, model, and overrides.
        """

        self._models.resolve(
            settings.provider, settings.model, "response", settings.requested
        )
        self._conversations.configure(scope, settings)

    def send(
        self, scope: ConversationScope, submitted: SubmittedInput
    ) -> GenerationAttempt:
        """Validate capacity before atomically committing input and a pending attempt.

        Args:
            scope:
                Complete required ownership.
            submitted:
                Validated new input.

        Returns:
            Durable pending attempt to pass to stream.
        """

        return self._prepare(scope, submitted)

    def continue_incomplete_turn(self, scope: ConversationScope) -> GenerationAttempt:
        """Reserve another attempt for the existing unmatched input.

        Args:
            scope:
                Complete required ownership.

        Returns:
            New attempt preserving all prior attempt provenance.
        """

        return self._prepare(scope, None)

    def retry_availability(self, scope: ConversationScope) -> RetryAvailability:
        """Return successful retry accounting for the selected final response.

        Args:
            scope:
                Complete required ownership.

        Returns:
            Durable retry accounting for the selected turn.

        Raises:
            IncompleteTurnError:
                If no completed persona response is selected.
        """

        history = self.history(scope)
        tail = history.messages[-1] if history.messages else None
        if tail is None or tail.role != "persona":
            raise IncompleteTurnError("No completed response is available to retry")
        return self._conversations.retry_availability(scope, tail.id)

    def retry_completed_response(self, scope: ConversationScope) -> GenerationAttempt:
        """Reserve a new attempt for the selected final persona response.

        Args:
            scope:
                Complete required ownership.

        Returns:
            Durable pending retry attempt.
        """

        history = self.history(scope)
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
            scope,
            retry_history,
            generation,
            None,
            retry_history.messages[-1].id,
        )
        return self._conversations.begin_retry(scope, generation, settings, tail.id)

    def stream(
        self, scope: ConversationScope, attempt_id: UUID
    ) -> Generator[str, None, None]:
        """Stream durable chunks, then atomically commit the completed response.

        The caller must exhaust or close this iterator. Unconsumed pending attempts
        and crashes are reconciled after their heartbeat expires.

        Args:
            scope:
                Complete required ownership.
            attempt_id:
                Pending attempt returned by send or continuation.

        Yields:
            Text already persisted as separate attempt output.
        """

        # A losing duplicate consumer must never stop the winning stream.
        attempt = self._conversations.claim(scope, attempt_id)
        output: Iterator[str] | None = None
        completed = False
        try:
            history = self.history(scope)
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
                scope,
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
            self._conversations.complete(scope, attempt_id)
            completed = True
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
        self, scope: ConversationScope, submitted: SubmittedInput | None
    ) -> GenerationAttempt:
        """Preflight an isolated prompt and fence any concurrent history change.

        Args:
            scope:
                Complete required ownership.
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

        history = self.history(scope)
        if any(a.status in {"pending", "streaming"} for a in history.attempts):
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
            scope, history, generation, submitted.content if submitted else None
        )
        expected_selected_leaf_id = tail.id if tail is not None else None
        return self._conversations.begin(
            scope,
            generation,
            settings,
            expected_selected_leaf_id,
            submitted,
        )

    def _prompt(
        self,
        scope: ConversationScope,
        history: ConversationHistory,
        generation: EffectiveGeneration,
        current_input: str | None,
        summary_path_leaf_id: UUID | None = None,
    ) -> tuple[PromptMessage, ...]:
        """Assemble required blocks and reject full-history overflow deterministically.

        Args:
            scope:
                Verified complete ownership.
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

        continuity = self._continuities.get(
            scope.identity_id, scope.persona_id, scope.continuity_id
        )
        if continuity.lifecycle != "active":
            raise ArchivedContinuityError("Archived continuity is read-only")
        persona = self._personas.get(scope.persona_id)
        identity = self._identities.get(scope.identity_id)
        counter = self._models.token_counter(generation.model.provider)
        current = self._summaries.current(scope, summary_path_leaf_id)
        for _ in range(len(history.messages) // 2 + 1):
            eligible = self._eligibility.select(history, current, current_input)
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
