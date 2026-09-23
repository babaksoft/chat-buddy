from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from uuid import UUID

from chat_buddy.chat.domain.exceptions import (
    InvalidGenerationAttemptTransitionError,
)
from chat_buddy.chat.domain.providers import (
    GenerationConfiguration,
    ModelId,
    ProviderId,
)


class GenerationAttemptStatus(str, Enum):
    """Lifecycle state of one response-generation invocation."""

    PENDING = "pending"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"

    @property
    def is_terminal(self) -> bool:
        """Return whether no further transition is permitted.

        Returns:
            ``True`` for a terminal lifecycle state; otherwise ``False``.
        """

        return self in {
            GenerationAttemptStatus.COMPLETED,
            GenerationAttemptStatus.FAILED,
            GenerationAttemptStatus.INTERRUPTED,
        }

    @property
    def is_open(self) -> bool:
        """Return whether the attempt can still produce a response.

        Returns:
            ``True`` for pending or streaming attempts; otherwise ``False``.
        """

        return self in {
            GenerationAttemptStatus.PENDING,
            GenerationAttemptStatus.STREAMING,
        }

    @property
    def is_retryable(self) -> bool:
        """Return whether the terminal outcome can seed a retry.

        Returns:
            ``True`` for failed or interrupted attempts; otherwise ``False``.
        """

        return self in {
            GenerationAttemptStatus.FAILED,
            GenerationAttemptStatus.INTERRUPTED,
        }


@dataclass(slots=True, frozen=True)
class GenerationAttemptRecord:
    """Persistence-neutral, immutable snapshot of a generation attempt."""

    id: UUID
    conversation_id: UUID
    source_user_message_id: UUID
    submitted_user_content: str
    provider_id: ProviderId
    model_id: ModelId
    effective_configuration: GenerationConfiguration
    status: GenerationAttemptStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    partial_content: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    assistant_message_id: UUID | None = None

    def __post_init__(self) -> None:
        """Validate the consistency of the immutable attempt snapshot.

        Raises:
            ValueError:
                If a lifecycle timestamp is not timezone-aware.
            InvalidGenerationAttemptTransitionError:
                If fields are inconsistent with the recorded lifecycle state
                or timestamp order.
        """

        if self.created_at.tzinfo is None:
            raise ValueError("Generation attempt timestamps must be timezone-aware.")
        for timestamp in (self.started_at, self.finished_at):
            if timestamp is not None and timestamp.tzinfo is None:
                raise ValueError(
                    "Generation attempt timestamps must be timezone-aware."
                )

        if not self.submitted_user_content.strip():
            raise ValueError("Submitted user content must be non-empty.")

        if self.status is GenerationAttemptStatus.PENDING:
            self._require(self.started_at is None, "Pending attempt cannot be started.")
            self._require(
                self.finished_at is None, "Pending attempt cannot be finished."
            )
        else:
            self._require(
                self.started_at is not None, "Started attempt needs started_at."
            )
        if self.started_at is not None:
            self._require(
                self.started_at >= self.created_at,
                "Attempt cannot start before it is created.",
            )

        if self.status.is_terminal:
            self._require(
                self.finished_at is not None, "Terminal attempt needs finished_at."
            )
        else:
            self._require(
                self.finished_at is None, "Active attempt cannot be finished."
            )
        if self.finished_at is not None and self.started_at is not None:
            self._require(
                self.finished_at >= self.started_at,
                "Attempt cannot finish before it starts.",
            )

        if self.status is GenerationAttemptStatus.COMPLETED:
            self._require(
                self.assistant_message_id is not None,
                "Completed attempt needs an assistant message.",
            )
            self._require(
                self.partial_content is None,
                "Completed attempt cannot retain partial content.",
            )
        else:
            self._require(
                self.assistant_message_id is None,
                "Only a completed attempt can have an assistant message.",
            )

        if self.status is GenerationAttemptStatus.FAILED:
            self._require(bool(self.error_code), "Failed attempt needs an error code.")
        else:
            self._require(
                self.error_code is None and self.error_detail is None,
                "Only a failed attempt can contain failure information.",
            )

    def start(self, *, at: datetime) -> GenerationAttemptRecord:
        """Move a pending attempt into streaming state.

        Args:
            at: Time at which response streaming started.

        Returns:
            A new streaming attempt snapshot.

        Raises:
            InvalidGenerationAttemptTransitionError:
                If the attempt is not pending or the timestamp precedes creation.
        """

        self._ensure_transition(GenerationAttemptStatus.STREAMING)
        return replace(
            self,
            status=GenerationAttemptStatus.STREAMING,
            started_at=at,
        )

    def checkpoint(self, partial_content: str) -> GenerationAttemptRecord:
        """Replace the recoverable partial output of a streaming attempt.

        Args:
            partial_content: Complete partial response accumulated so far.

        Returns:
            A new attempt snapshot containing the partial response.

        Raises:
            InvalidGenerationAttemptTransitionError:
                If the attempt is not streaming.
        """

        if self.status is not GenerationAttemptStatus.STREAMING:
            raise InvalidGenerationAttemptTransitionError(
                "Only a streaming attempt can be checkpointed."
            )

        return replace(self, partial_content=partial_content or None)

    def complete(
        self, *, assistant_message_id: UUID, at: datetime
    ) -> GenerationAttemptRecord:
        """Complete a streaming attempt and link its assistant message.

        Args:
            assistant_message_id:
                Identifier of the completed assistant message.
            at:
                Time at which generation completed.

        Returns:
            A new completed attempt snapshot.

        Raises:
            InvalidGenerationAttemptTransitionError:
                If the attempt is not streaming or the timestamp precedes its start.
        """

        self._ensure_transition(GenerationAttemptStatus.COMPLETED)
        return replace(
            self,
            status=GenerationAttemptStatus.COMPLETED,
            partial_content=None,
            assistant_message_id=assistant_message_id,
            finished_at=at,
        )

    def fail(
        self,
        *,
        error_code: str,
        at: datetime,
        error_detail: str | None = None,
        partial_content: str | None = None,
    ) -> GenerationAttemptRecord:
        """Terminate a streaming attempt with normalized safe failure data.

        Args:
            error_code:
                Stable normalized failure code.
            at:
                Time at which generation failed.
            error_detail:
                Optional safe user-facing failure detail.
            partial_content:
                Optional complete partial response accumulated so far.

        Returns:
            A new failed attempt snapshot.

        Raises:
            InvalidGenerationAttemptTransitionError:
                If the attempt is not streaming, the error code is blank,
                or the timestamp precedes its start.
        """

        self._ensure_transition(GenerationAttemptStatus.FAILED)
        return replace(
            self,
            status=GenerationAttemptStatus.FAILED,
            error_code=error_code,
            error_detail=error_detail,
            partial_content=partial_content or self.partial_content,
            finished_at=at,
        )

    def interrupt(
        self, *, at: datetime, partial_content: str | None = None
    ) -> GenerationAttemptRecord:
        """Terminate a streaming attempt because its consumer stopped.

        Args:
            at:
                Time at which generation was interrupted.
            partial_content:
                Optional complete partial response accumulated so far.

        Returns:
            A new interrupted attempt snapshot.

        Raises:
            InvalidGenerationAttemptTransitionError:
                If the attempt is not streaming or the timestamp precedes its start.
        """

        self._ensure_transition(GenerationAttemptStatus.INTERRUPTED)
        return replace(
            self,
            status=GenerationAttemptStatus.INTERRUPTED,
            partial_content=partial_content or self.partial_content,
            finished_at=at,
        )

    def _ensure_transition(self, target: GenerationAttemptStatus) -> None:
        """Ensure that the target state is reachable from the current state.

        Args:
            target: Lifecycle state requested by an operation.

        Raises:
            InvalidGenerationAttemptTransitionError:
                If the transition is not allowed by the generation-attempt lifecycle.
        """

        allowed = {
            GenerationAttemptStatus.PENDING: {GenerationAttemptStatus.STREAMING},
            GenerationAttemptStatus.STREAMING: {
                GenerationAttemptStatus.COMPLETED,
                GenerationAttemptStatus.FAILED,
                GenerationAttemptStatus.INTERRUPTED,
            },
        }
        if target not in allowed.get(self.status, set()):
            raise InvalidGenerationAttemptTransitionError(
                f"Cannot transition generation attempt from "
                f"{self.status.value} to {target.value}."
            )

    @staticmethod
    def _require(condition: bool, message: str) -> None:
        """Raise a lifecycle error when an invariant does not hold.

        Args:
            condition:
                Invariant result to enforce.
            message:
                Explanation used when the invariant fails.

        Raises:
            InvalidGenerationAttemptTransitionError:
                If ``condition`` is false.
        """

        if not condition:
            raise InvalidGenerationAttemptTransitionError(message)
