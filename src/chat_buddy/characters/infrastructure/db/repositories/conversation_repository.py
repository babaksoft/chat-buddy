"""Short transactions with continuity locks and immutable provenance."""

from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    AlternativeGroup,
    ArchivedContinuityError,
    AttemptConflictError,
    AttemptStatus,
    ConversationGraph,
    ConversationHistory,
    ConversationNotFoundError,
    ConversationScope,
    ConversationSettings,
    EffectiveGeneration,
    EvolutionStrategyId,
    GenerationAttempt,
    GraphAction,
    GraphActionRequest,
    IncompleteTurnError,
    InvalidParentError,
    InvalidProviderResponseError,
    Message,
    MessageNode,
    ResponseProvenance,
    ResponseStyleSnapshot,
    RetryAvailability,
    RetryLimitError,
    SelectedPath,
    StaleSelectionError,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.models import (
    ContinuityModel,
    ConversationModel,
    GenerationAttemptModel,
    MessageModel,
)


class DbConversationRepository:
    """Persist selected-path turns under the archive serialization lock."""

    _RESPONSE_STYLE = ResponseStyleSnapshot(
        name="ongoing.default",
        version="1.0.0",
        instruction=(
            "Respond as the persona in a natural conversation. Use clear text and "
            "preserve the authored identity and relationship boundaries."
        ),
    )
    _EVOLUTION_STRATEGY = EvolutionStrategyId(
        name="baseline.no_change", version="1.0.0"
    )

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Initialize the conversation repository.

        Args:
            session_factory:
                Factory used for creating database sessions.
        """

        self._factory = session_factory

    def history(self, scope: ConversationScope) -> ConversationHistory:
        """Read committed history and attempt provenance.

        Args:
            scope:
                Complete required ownership.

        Returns:
            Detached domain snapshot.
        """

        with self._factory() as session, session.begin():
            row = self._owned(session, scope)
            return self._history(session, scope, row)

    def selected_path(self, scope: ConversationScope) -> SelectedPath:
        """Read only the selected root-to-leaf ancestry.

        Args:
            scope:
                Complete required ownership.

        Returns:
            Detached selected path excluding every sibling.
        """

        with self._factory() as session, session.begin():
            row = self._owned(session, scope)
            return self._selected_path(session, scope, row)

    def graph(self, scope: ConversationScope) -> ConversationGraph:
        """Read every immutable node in deterministic creation order.

        Args:
            scope:
                Complete required ownership.

        Returns:
            Detached complete graph inspection snapshot.
        """

        with self._factory() as session, session.begin():
            row = self._owned(session, scope)
            nodes = session.scalars(
                select(MessageModel)
                .where(
                    MessageModel.conversation_id == scope.conversation_id,
                    MessageModel.continuity_id == scope.continuity_id,
                )
                .order_by(MessageModel.created_at, MessageModel.id)
            )
            return ConversationGraph(
                scope=scope,
                selected_leaf_id=row.selected_leaf_id,
                nodes=tuple(self._node(scope, node) for node in nodes),
            )

    def alternatives(
        self, scope: ConversationScope, user_message_id: UUID
    ) -> AlternativeGroup:
        """Read completed persona siblings for one owned user node.

        Args:
            scope:
                Complete required ownership.
            user_message_id:
                Exact shared user parent.

        Returns:
            Deterministically ordered completed alternatives.

        Raises:
            InvalidParentError:
                If the parent is absent, foreign, or not a user node.
        """

        with self._factory() as session, session.begin():
            self._owned(session, scope)
            parent = session.scalar(
                select(MessageModel).where(
                    MessageModel.id == user_message_id,
                    MessageModel.conversation_id == scope.conversation_id,
                    MessageModel.continuity_id == scope.continuity_id,
                )
            )
            if parent is None or parent.role != "user":
                raise InvalidParentError(
                    "Alternative parent must be an owned user node"
                )
            siblings = session.scalars(
                select(MessageModel)
                .where(
                    MessageModel.conversation_id == scope.conversation_id,
                    MessageModel.continuity_id == scope.continuity_id,
                    MessageModel.parent_id == user_message_id,
                    MessageModel.role == "persona",
                )
                .order_by(MessageModel.created_at, MessageModel.id)
            )
            return AlternativeGroup(
                scope=scope,
                user_message_id=user_message_id,
                responses=tuple(self._node(scope, sibling) for sibling in siblings),
            )

    def select_leaf(
        self,
        scope: ConversationScope,
        message_id: UUID,
        expected_selected_leaf_id: UUID | None,
    ) -> SelectedPath:
        """Select an exact owned persona node under a compare-and-swap guard.

        Args:
            scope:
                Complete required ownership.
            message_id:
                Exact persona node to select.
            expected_selected_leaf_id:
                Last selected leaf observed by the caller.

        Returns:
            Newly selected root-to-node ancestry.

        Raises:
            StaleSelectionError:
                If the selected leaf changed since the caller read it.
            InvalidParentError:
                If the target is absent, foreign, or not a persona node.
        """

        with self._factory() as session, session.begin():
            row = self._owned(session, scope, writable=True)
            if row.selected_leaf_id != expected_selected_leaf_id:
                raise StaleSelectionError("Selected conversation path changed")
            target = session.scalar(
                select(MessageModel).where(
                    MessageModel.id == message_id,
                    MessageModel.conversation_id == scope.conversation_id,
                    MessageModel.continuity_id == scope.continuity_id,
                )
            )
            if target is None or target.role != "persona":
                raise InvalidParentError("Selected leaf must be an owned persona node")
            row.selected_leaf_id = target.id
            session.flush()
            return self._selected_path(session, scope, row)

    def apply_action(self, request: GraphActionRequest) -> SelectedPath:
        """Apply exact-future selection or branching under one ownership lock.

        Args:
            request:
                Fully owned graph action with its compare-and-swap guard.

        Returns:
            Newly selected ancestry.

        Raises:
            AttemptConflictError:
                If a generation attempt is active.
            InvalidParentError:
                If the target is foreign, ambiguous, or invalid for the action.
            StaleSelectionError:
                If the selected leaf changed after the caller observed it.
        """

        if request.action not in {
            GraphAction.ALTERNATIVE_SELECTION,
            GraphAction.BRANCH_FROM_HERE,
        }:
            raise ValueError("Only selection and branching are graph actions")
        if request.target_message_id is None:
            raise ValueError("A graph action requires an exact target")

        scope = request.scope
        with self._factory() as session, session.begin():
            row = self._owned(session, scope, writable=True)
            if row.selected_leaf_id != request.expected_selected_leaf_id:
                raise StaleSelectionError("Selected conversation path changed")
            active_attempt = session.scalar(
                select(GenerationAttemptModel.id)
                .where(
                    GenerationAttemptModel.conversation_id == scope.conversation_id,
                    GenerationAttemptModel.continuity_id == scope.continuity_id,
                    GenerationAttemptModel.status.in_(["pending", "streaming"]),
                )
                .limit(1)
            )
            if active_attempt is not None:
                raise AttemptConflictError("An attempt is already active")

            target = session.scalar(
                select(MessageModel).where(
                    MessageModel.id == request.target_message_id,
                    MessageModel.conversation_id == scope.conversation_id,
                    MessageModel.continuity_id == scope.continuity_id,
                    MessageModel.role == "persona",
                )
            )
            if target is None:
                raise InvalidParentError("Graph target must be an owned persona node")

            path = self._selected_path(session, scope, row)
            selected_ids = {message.id for message in path.messages}
            if target.id == row.selected_leaf_id:
                raise InvalidParentError("The current leaf is already selected")

            if request.action == GraphAction.BRANCH_FROM_HERE:
                if target.id not in selected_ids:
                    raise InvalidParentError(
                        "A branch point must be on the selected path"
                    )
            else:
                if target.id in selected_ids:
                    raise InvalidParentError(
                        "Use branching for an older selected-path persona node"
                    )
                child_id = session.scalar(
                    select(MessageModel.id)
                    .where(
                        MessageModel.conversation_id == scope.conversation_id,
                        MessageModel.continuity_id == scope.continuity_id,
                        MessageModel.parent_id == target.id,
                    )
                    .limit(1)
                )
                if child_id is not None:
                    raise InvalidParentError(
                        "Select the exact saved descendant leaf, not an ambiguous future"
                    )

            row.selected_leaf_id = target.id
            session.flush()
            return self._selected_path(session, scope, row)

    def configure(
        self, scope: ConversationScope, settings: ConversationSettings
    ) -> None:
        """Save next-attempt defaults on a writable conversation.

        Args:
            scope:
                Complete required ownership.
            settings:
                Validated requested selection.
        """

        with self._factory() as session, session.begin():
            row = self._owned(session, scope, writable=True)
            row.generation_settings = settings.model_dump(mode="json")

    def begin(
        self,
        scope: ConversationScope,
        generation: EffectiveGeneration,
        settings: ConversationSettings,
        expected_selected_leaf_id: UUID | None,
        submitted: SubmittedInput | None,
    ) -> GenerationAttempt:
        """Atomically reserve an attempt and optionally append its user message.

        Args:
            scope:
                Complete required ownership.
            generation:
                Immutable effective response configuration.
            settings:
                Current requested selection to persist.
            expected_selected_leaf_id:
                Last selected leaf observed during prompt preflight.
            submitted:
                New input, or None to continue the existing unmatched tail.

        Returns:
            Detached domain snapshot.
        """

        if generation.capability != "response":
            raise ValueError("A response generation is required")

        with self._factory() as session, session.begin():
            row = self._owned(session, scope, writable=True)
            if (
                row.generation_settings is not None
                and row.generation_settings != settings.model_dump(mode="json")
            ):
                raise AttemptConflictError("Generation defaults changed; prepare again")
            history = self._history(session, scope, row)
            if any(a.status in {"pending", "streaming"} for a in history.attempts):
                raise AttemptConflictError("An attempt is already active")
            tail = history.messages[-1] if history.messages else None
            if row.selected_leaf_id != expected_selected_leaf_id:
                raise AttemptConflictError("History changed; prepare the prompt again")
            now = datetime.now(UTC)
            if submitted is not None:
                if tail is not None and tail.role == "user":
                    raise IncompleteTurnError("Continue the unmatched user message")
                message = MessageModel(
                    conversation_id=scope.conversation_id,
                    continuity_id=scope.continuity_id,
                    role="user",
                    content=submitted.content,
                    parent_id=tail.id if tail is not None else None,
                    created_at=now,
                )
                session.add(message)
                session.flush()
                row.selected_leaf_id = message.id
                user_id, content = message.id, message.content
            else:
                if tail is None or tail.role != "user":
                    raise IncompleteTurnError("There is no incomplete turn to continue")
                user_id, content = tail.id, tail.content
            row.generation_settings = settings.model_dump(mode="json")
            attempt = GenerationAttemptModel(
                conversation_id=scope.conversation_id,
                continuity_id=scope.continuity_id,
                user_message_id=user_id,
                selection_guard_id=user_id,
                submitted_input=content,
                generation=generation.model_dump(mode="json"),
                status="pending",
                incomplete_output="",
                created_at=now,
                updated_at=now,
            )
            session.add(attempt)
            session.flush()
            return self._attempt(scope, attempt)

    def retry_availability(
        self, scope: ConversationScope, persona_message_id: UUID
    ) -> RetryAvailability:
        """Count completed siblings for the selected final response.

        Args:
            scope:
                Complete required ownership.
            persona_message_id:
                Selected final persona response.

        Returns:
            Durable successful retry accounting.

        Raises:
            InvalidParentError:
                If the target is not the selected owned persona leaf.
        """

        with self._factory() as session, session.begin():
            row = self._owned(session, scope)
            target = self._selected_persona_message(
                session, scope, row, persona_message_id
            )
            return self._retry_availability(session, scope, target)

    def begin_retry(
        self,
        scope: ConversationScope,
        generation: EffectiveGeneration,
        settings: ConversationSettings,
        expected_selected_leaf_id: UUID,
    ) -> GenerationAttempt:
        """Atomically reserve a bounded retry without changing selection.

        Args:
            scope:
                Complete required ownership.
            generation:
                Immutable effective response configuration.
            settings:
                Current requested selection to persist.
            expected_selected_leaf_id:
                Selected final persona response observed during preflight.

        Returns:
            Detached pending retry attempt.

        Raises:
            RetryLimitError:
                If three successful retries already exist.
        """

        if generation.capability != "response":
            raise ValueError("A response generation is required")

        with self._factory() as session, session.begin():
            row = self._owned(session, scope, writable=True)
            if (
                row.generation_settings is not None
                and row.generation_settings != settings.model_dump(mode="json")
            ):
                raise AttemptConflictError("Generation defaults changed; prepare again")

            history = self._history(session, scope, row)
            if any(
                attempt.status in {"pending", "streaming"}
                for attempt in history.attempts
            ):
                raise AttemptConflictError("An attempt is already active")
            if row.selected_leaf_id != expected_selected_leaf_id:
                raise AttemptConflictError("History changed; prepare the prompt again")

            target = self._selected_persona_message(
                session, scope, row, expected_selected_leaf_id
            )
            availability = self._retry_availability(session, scope, target)
            if availability.retries_remaining == 0:
                raise RetryLimitError("The completed response has no retries remaining")

            parent = session.get(MessageModel, target.parent_id)
            if parent is None or parent.role != "user":
                raise InvalidParentError("Persona response has no owned user parent")

            now = datetime.now(UTC)
            row.generation_settings = settings.model_dump(mode="json")
            attempt = GenerationAttemptModel(
                conversation_id=scope.conversation_id,
                continuity_id=scope.continuity_id,
                user_message_id=parent.id,
                selection_guard_id=target.id,
                submitted_input=parent.content,
                generation=generation.model_dump(mode="json"),
                status="pending",
                incomplete_output="",
                created_at=now,
                updated_at=now,
            )
            session.add(attempt)
            session.flush()
            return self._attempt(scope, attempt)

    def claim(self, scope: ConversationScope, attempt_id: UUID) -> GenerationAttempt:
        """Atomically transition a pending attempt to streaming.

        Args:
            scope:
                Complete required ownership.
            attempt_id:
                Pending attempt identifier.

        Returns:
            Detached domain snapshot.
        """

        with self._factory() as session, session.begin():
            self._owned(session, scope, writable=True)
            attempt = self._find_attempt(session, scope, attempt_id)
            self._require_status(attempt, "pending")
            attempt.status = "streaming"
            attempt.updated_at = datetime.now(UTC)
            session.flush()
            return self._attempt(scope, attempt)

    def append(self, scope: ConversationScope, attempt_id: UUID, chunk: str) -> None:
        """Persist progress and refresh its heartbeat.

        Args:
            scope:
                Complete required ownership.
            attempt_id:
                Streaming attempt identifier.
            chunk:
                New output text.
        """

        with self._factory() as session, session.begin():
            self._owned(session, scope, writable=True)
            attempt = self._find_attempt(session, scope, attempt_id)
            self._require_status(attempt, "streaming")
            attempt.incomplete_output += chunk
            attempt.updated_at = datetime.now(UTC)

    def complete(self, scope: ConversationScope, attempt_id: UUID) -> Message:
        """Atomically append a persona message and complete its attempt.

        Args:
            scope:
                Complete required ownership.
            attempt_id:
                Streaming attempt identifier.

        Returns:
            Detached domain snapshot.
        """

        with self._factory() as session, session.begin():
            row = self._owned(session, scope, writable=True)
            attempt = self._find_attempt(session, scope, attempt_id)
            self._require_status(attempt, "streaming")
            if row.selected_leaf_id != attempt.selection_guard_id:
                raise AttemptConflictError("Attempt no longer owns the selected tail")
            if not attempt.incomplete_output.strip():
                raise InvalidProviderResponseError(
                    "Provider returned an empty response"
                )
            if attempt.selection_guard_id != attempt.user_message_id:
                successful_responses = session.scalar(
                    select(func.count(MessageModel.id)).where(
                        MessageModel.conversation_id == scope.conversation_id,
                        MessageModel.continuity_id == scope.continuity_id,
                        MessageModel.parent_id == attempt.user_message_id,
                        MessageModel.role == "persona",
                    )
                )
                if successful_responses is None or successful_responses >= 4:
                    raise RetryLimitError(
                        "The completed response has no retries remaining"
                    )
            now = datetime.now(UTC)
            message = MessageModel(
                conversation_id=scope.conversation_id,
                continuity_id=scope.continuity_id,
                role="persona",
                content=attempt.incomplete_output,
                parent_id=attempt.user_message_id,
                response_provenance=ResponseProvenance(
                    generation=EffectiveGeneration.model_validate(attempt.generation),
                    response_style=self._RESPONSE_STYLE,
                    evolution_strategy=self._EVOLUTION_STRATEGY,
                    attempt_id=attempt.id,
                ).model_dump(mode="json"),
                created_at=now,
            )
            session.add(message)
            session.flush()
            row.selected_leaf_id = message.id
            attempt.persona_message_id = message.id
            attempt.status = "completed"
            attempt.updated_at = attempt.finished_at = now
            session.flush()
            path = self._selected_path(session, scope, row)
            return self._message(path.messages[-1], len(path.messages))

    @staticmethod
    def _selected_persona_message(
        session: Session,
        scope: ConversationScope,
        conversation: ConversationModel,
        persona_message_id: UUID,
    ) -> MessageModel:
        """Resolve an exact selected persona leaf within full ownership.

        Args:
            session:
                Current transaction.
            scope:
                Complete required ownership.
            conversation:
                Owned conversation row.
            persona_message_id:
                Expected selected persona identifier.

        Returns:
            Selected persona row.

        Raises:
            InvalidParentError:
                If the identifier is not the selected owned persona leaf.
        """

        target = session.scalar(
            select(MessageModel).where(
                MessageModel.id == persona_message_id,
                MessageModel.conversation_id == scope.conversation_id,
                MessageModel.continuity_id == scope.continuity_id,
                MessageModel.role == "persona",
            )
        )
        if target is None or conversation.selected_leaf_id != target.id:
            raise InvalidParentError("Retry target must be the selected persona leaf")
        return target

    @staticmethod
    def _retry_availability(
        session: Session, scope: ConversationScope, target: MessageModel
    ) -> RetryAvailability:
        """Count successful responses sharing the target's user parent.

        Args:
            session:
                Current transaction.
            scope:
                Complete required ownership.
            target:
                Selected owned persona response.

        Returns:
            Durable successful retry accounting.
        """

        if target.parent_id is None:
            raise InvalidParentError("Persona response has no user parent")
        count = session.scalar(
            select(func.count(MessageModel.id)).where(
                MessageModel.conversation_id == scope.conversation_id,
                MessageModel.continuity_id == scope.continuity_id,
                MessageModel.parent_id == target.parent_id,
                MessageModel.role == "persona",
            )
        )
        return RetryAvailability(
            user_message_id=target.parent_id,
            successful_response_count=count or 1,
        )

    def stop(
        self,
        scope: ConversationScope,
        attempt_id: UUID,
        status: Literal["failed", "interrupted"],
    ) -> None:
        """Terminate an open attempt without modifying committed history.

        Args:
            scope:
                Complete required ownership.
            attempt_id:
                Attempt to terminate.
            status:
                Terminal failure or interruption status.
        """

        with self._factory() as session, session.begin():
            self._owned(session, scope)
            attempt = self._find_attempt(session, scope, attempt_id)
            if attempt.status in {"pending", "streaming"}:
                attempt.status = status
                attempt.updated_at = attempt.finished_at = datetime.now(UTC)

    def reconcile(
        self, scope: ConversationScope, inactive_before: datetime
    ) -> ConversationHistory:
        """Interrupt expired attempts while fencing their late output.

        Args:
            scope:
                Complete required ownership.
            inactive_before:
                Only heartbeats at or before this UTC cutoff are abandoned.

        Returns:
            Detached domain snapshot.
        """

        with self._factory() as session, session.begin():
            row = self._owned(session, scope)
            attempts = session.scalars(
                select(GenerationAttemptModel).where(
                    GenerationAttemptModel.conversation_id == scope.conversation_id,
                    GenerationAttemptModel.continuity_id == scope.continuity_id,
                    GenerationAttemptModel.status.in_(["pending", "streaming"]),
                    GenerationAttemptModel.updated_at <= inactive_before,
                )
            )
            for attempt in attempts:
                attempt.status = "interrupted"
                attempt.updated_at = attempt.finished_at = datetime.now(UTC)
            session.flush()
            return self._history(session, scope, row)

    @staticmethod
    def _owned(
        session: Session, scope: ConversationScope, writable: bool = False
    ) -> ConversationModel:
        """Lock continuity first so all writers serialize with archival.

        Args:
            session:
                Current transaction.
            scope:
                Required ownership.
            writable:
                Whether archived lifecycle must be rejected.

        Returns:
            Owned conversation row.

        Raises:
            ConversationNotFoundError:
                If any ownership identifier is foreign.
            ArchivedContinuityError:
                If a write targets an archive.
        """

        continuity = session.scalar(
            select(ContinuityModel)
            .where(
                ContinuityModel.id == scope.continuity_id,
                ContinuityModel.identity_id == scope.identity_id,
                ContinuityModel.persona_id == scope.persona_id,
            )
            .with_for_update()
        )
        if continuity is None:
            raise ConversationNotFoundError("Conversation ownership does not match")
        row = session.scalar(
            select(ConversationModel).where(
                ConversationModel.id == scope.conversation_id,
                ConversationModel.continuity_id == scope.continuity_id,
                ConversationModel.identity_id == scope.identity_id,
                ConversationModel.persona_id == scope.persona_id,
            )
        )
        if row is None:
            raise ConversationNotFoundError("Conversation ownership does not match")
        if writable and continuity.lifecycle != "active":
            raise ArchivedContinuityError("Archived continuity is read-only")
        return row

    @staticmethod
    def _find_attempt(
        session: Session, scope: ConversationScope, attempt_id: UUID
    ) -> GenerationAttemptModel:
        """Read an attempt only within its conversation ownership.

        Args:
            session:
                Current transaction.
            scope:
                Required ownership.
            attempt_id:
                Requested attempt.

        Returns:
            Owned attempt row.

        Raises:
            ConversationNotFoundError:
                If the attempt belongs elsewhere.
        """

        row = session.scalar(
            select(GenerationAttemptModel).where(
                GenerationAttemptModel.id == attempt_id,
                GenerationAttemptModel.conversation_id == scope.conversation_id,
                GenerationAttemptModel.continuity_id == scope.continuity_id,
            )
        )
        if row is None:
            raise ConversationNotFoundError("Attempt ownership does not match")
        return row

    @staticmethod
    def _require_status(attempt: GenerationAttemptModel, status: str) -> None:
        """Fence stale or duplicate attempt mutations.

        Args:
            attempt:
                Owned attempt row.
            status:
                Required source state.

        Raises:
            AttemptConflictError:
                If the attempt has already moved on.
        """

        if attempt.status != status:
            raise AttemptConflictError("Attempt is no longer in the required state")

    @classmethod
    def _history(
        cls, session: Session, scope: ConversationScope, row: ConversationModel
    ) -> ConversationHistory:
        """Read only the owned messages and attempts in deterministic order.

        Args:
            session:
                Current transaction.
            scope:
                Required ownership.
            row:
                Owned conversation.

        Returns:
            Detached immutable history.
        """

        path = cls._selected_path(session, scope, row)
        attempts = session.scalars(
            select(GenerationAttemptModel)
            .where(
                GenerationAttemptModel.conversation_id == scope.conversation_id,
                GenerationAttemptModel.continuity_id == scope.continuity_id,
            )
            .order_by(GenerationAttemptModel.created_at, GenerationAttemptModel.id)
        )
        return ConversationHistory(
            scope=scope,
            settings=(
                ConversationSettings.model_validate(row.generation_settings)
                if row.generation_settings
                else None
            ),
            messages=tuple(
                cls._message(node, sequence)
                for sequence, node in enumerate(path.messages, start=1)
            ),
            attempts=tuple(cls._attempt(scope, attempt) for attempt in attempts),
        )

    @staticmethod
    def _message(node: MessageNode, sequence: int) -> Message:
        """Detach a committed message from persistence.

        Args:
            node:
                Selected graph node.
            sequence:
                Derived root-to-leaf position.

        Returns:
            Immutable message snapshot.
        """

        return Message(
            id=node.id,
            scope=node.scope,
            sequence=sequence,
            role=node.role,
            content=node.content,
            created_at=node.created_at,
        )

    @classmethod
    def _selected_path(
        cls, session: Session, scope: ConversationScope, row: ConversationModel
    ) -> SelectedPath:
        """Traverse parents from the selected leaf without persisted positions.

        Args:
            session:
                Current transaction.
            scope:
                Verified complete ownership.
            row:
                Owned conversation.

        Returns:
            Detached selected root-to-leaf ancestry.

        Raises:
            InvalidParentError:
                If persisted graph ownership or ancestry is invalid.
        """

        if row.selected_leaf_id is None:
            return SelectedPath(scope=scope, selected_leaf_id=None, messages=())
        rows = tuple(
            session.scalars(
                select(MessageModel).where(
                    MessageModel.conversation_id == scope.conversation_id,
                    MessageModel.continuity_id == scope.continuity_id,
                )
            )
        )
        by_id = {message.id: message for message in rows}
        current = by_id.get(row.selected_leaf_id)
        if current is None:
            raise InvalidParentError("Selected leaf is absent from its conversation")
        reversed_path: list[MessageNode] = []
        seen: set[UUID] = set()
        while current is not None:
            if current.id in seen:
                raise InvalidParentError("Conversation graph contains a cycle")
            seen.add(current.id)
            reversed_path.append(cls._node(scope, current))
            if current.parent_id is None:
                break
            current = by_id.get(current.parent_id)
            if current is None:
                raise InvalidParentError("Message parent is absent or foreign")
        try:
            return SelectedPath(
                scope=scope,
                selected_leaf_id=row.selected_leaf_id,
                messages=tuple(reversed(reversed_path)),
            )
        except ValueError as error:
            raise InvalidParentError(str(error)) from error

    @staticmethod
    def _node(scope: ConversationScope, row: MessageModel) -> MessageNode:
        """Detach one immutable persisted graph node.

        Args:
            scope:
                Verified complete ownership.
            row:
                Persisted graph node.

        Returns:
            Immutable graph node.
        """

        return MessageNode(
            id=row.id,
            scope=scope,
            parent_id=row.parent_id,
            role=cast(Literal["user", "persona"], row.role),
            content=row.content,
            created_at=_utc(row.created_at),
            response_provenance=(
                ResponseProvenance.model_validate(row.response_provenance)
                if row.response_provenance is not None
                else None
            ),
        )

    @staticmethod
    def _attempt(
        scope: ConversationScope, row: GenerationAttemptModel
    ) -> GenerationAttempt:
        """Detach immutable provenance and current recovery status.

        Args:
            scope:
                Verified ownership.
            row:
                Owned ledger row.

        Returns:
            Immutable attempt snapshot.
        """

        return GenerationAttempt(
            id=row.id,
            scope=scope,
            user_message_id=row.user_message_id,
            submitted_input=row.submitted_input,
            generation=EffectiveGeneration.model_validate(row.generation),
            status=cast(AttemptStatus, row.status),
            incomplete_output=row.incomplete_output,
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
            finished_at=(_utc(row.finished_at) if row.finished_at else None),
        )


def _utc(value: datetime) -> datetime:
    """Normalize aware PostgreSQL and naive SQLite timestamps.

    Args:
        value:
            Database timestamp stored in UTC.

    Returns:
        UTC-aware timestamp preserving the original instant.
    """

    return (
        value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    )
