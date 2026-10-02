"""Durable bounded Ongoing generation with isolated incomplete-turn recovery."""

from collections.abc import Generator, Iterator
from datetime import UTC, datetime, timedelta
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
    ConversationHistory,
    ConversationRepository,
    ConversationScope,
    ConversationSettings,
    EffectiveGeneration,
    GenerationAttempt,
    IdentityRepository,
    IncompleteTurnError,
    ModelRegistry,
    PersonaRepository,
    PromptMessage,
    SubmittedInput,
    SummaryRepository,
)


class ConversationService:
    """Orchestrate short repository operations around external streaming calls."""

    def __init__(
        self,
        conversations: ConversationRepository,
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

    def history(self, scope: ConversationScope) -> ConversationHistory:
        """Inspect committed history and incomplete output separately.

        Args:
            scope:
                Complete required ownership.

        Returns:
            Detached durable history, including archives.
        """

        return self._conversations.history(scope)

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
            prompt = self._prompt(scope, history, attempt.generation, None)
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
        return self._conversations.begin(
            scope, generation, settings, tail.sequence if tail else 0, submitted
        )

    def _prompt(
        self,
        scope: ConversationScope,
        history: ConversationHistory,
        generation: EffectiveGeneration,
        current_input: str | None,
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
        active = self._summaries.active(scope)
        for _ in range(len(history.messages) // 2 + 1):
            eligible = self._eligibility.select(history, active, current_input)
            selection = self._budgeter.assemble(
                persona, identity, continuity, eligible, generation, counter
            )
            if not selection.omitted_turns:
                return selection.prompt
            active = self._summaries.advance(scope, active, selection.omitted_turns)
        raise ContextCapacityError(
            "Conversation summary did not make bounded progress."
        )
