"""Immutable sole-path messages, ownership, defaults, and attempt provenance."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chat_buddy.characters.domain.continuity import ContinuityMode
from chat_buddy.characters.domain.llm import (
    EffectiveGeneration,
    GenerationConfiguration,
)


class ConversationScope(BaseModel):
    """Explicit ownership required for every conversation operation.

    Attributes:
        identity_id:
            Expected identity owner.
        persona_id:
            Expected persona owner.
        continuity_id:
            Expected continuity owner.
        conversation_id:
            Sole conversation identifier.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity_id: UUID = Field(description="Expected identity owner.")
    persona_id: UUID = Field(description="Expected persona owner.")
    continuity_id: UUID = Field(description="Expected continuity owner.")
    conversation_id: UUID = Field(description="Sole conversation identifier.")


class ConversationTarget(BaseModel):
    """Mode-owned target for one Characters conversation.

    Attributes:
        scope:
            Complete profile, continuity, and conversation ownership.
        mode:
            Mode whose policy and prompt assembly govern the conversation.
        scene_id:
            Required Storyline scene owner and absent for Ongoing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ConversationScope = Field(description="Complete conversation ownership.")
    mode: ContinuityMode = Field(description="Governing continuity mode.")
    scene_id: UUID | None = Field(
        default=None, description="Owning Storyline scene when applicable."
    )

    @model_validator(mode="after")
    def validate_mode_owner(self) -> Self:
        """Require exactly the owner needed by each supported mode.

        Returns:
            The validated immutable target.

        Raises:
            ValueError:
                If Ongoing has a scene or Storyline has none.
        """

        if self.mode == ContinuityMode.ONGOING and self.scene_id is not None:
            raise ValueError("Ongoing conversations do not belong to scenes")
        if self.mode == ContinuityMode.STORYLINE and self.scene_id is None:
            raise ValueError("Storyline conversations require a scene owner")
        if self.mode == ContinuityMode.TIMELINE:
            raise ValueError("Timeline conversation targets are not available")
        return self


class SubmittedInput(BaseModel):
    """Validated exact user text, retaining meaningful whitespace.

    Attributes:
        content:
            Nonblank submitted message, at most 32768 characters.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str = Field(
        min_length=1,
        max_length=32768,
        pattern=r"\S",
        description="Exact submitted input.",
    )


class ConversationSettings(BaseModel):
    """Persisted requested selection for the next attempt.

    Attributes:
        provider:
            Configured provider key.
        model:
            Configured model name.
        requested:
            Requested generation overrides.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(min_length=1, max_length=64, description="Provider key.")
    model: str = Field(min_length=1, max_length=256, description="Model name.")
    requested: GenerationConfiguration = Field(
        default_factory=GenerationConfiguration, description="Requested overrides."
    )


class Message(BaseModel):
    """Committed append-only message on the sole conversation path.

    Attributes:
        id:
            Stable message identifier.
        scope:
            Complete ownership.
        sequence:
            Positive deterministic path position.
        role:
            User or persona speaker.
        content:
            Exact committed text.
        created_at:
            Commit timestamp in UTC.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(description="Stable identifier.")
    scope: ConversationScope = Field(description="Complete ownership.")
    sequence: int = Field(gt=0, description="Path position.")
    role: Literal["user", "persona"] = Field(description="Speaker.")
    content: str = Field(min_length=1, description="Exact committed text.")
    created_at: datetime = Field(description="UTC timestamp.")


AttemptStatus = Literal["pending", "streaming", "completed", "failed", "interrupted"]


class GenerationAttempt(BaseModel):
    """Durable attempt snapshot distinct from committed persona messages.

    Attributes:
        id:
            Stable attempt identifier.
        scope:
            Complete ownership.
        user_message_id:
            Existing unmatched user message.
        submitted_input:
            Exact input retained for provenance.
        generation:
            Immutable effective provider/model/configuration and budget.
        status:
            Current lifecycle status.
        incomplete_output:
            Accumulated output retained independently of messages.
        created_at:
            Submission timestamp.
        updated_at:
            Latest progress or terminal timestamp.
        finished_at:
            Terminal timestamp when present.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(description="Stable attempt identifier.")
    scope: ConversationScope = Field(description="Complete ownership.")
    user_message_id: UUID = Field(description="Existing user message.")
    submitted_input: str = Field(description="Exact input provenance.")
    generation: EffectiveGeneration = Field(
        description="Immutable effective selection."
    )
    status: AttemptStatus = Field(description="Lifecycle status.")
    incomplete_output: str = Field(description="Accumulated output outside history.")
    created_at: datetime = Field(description="Submission timestamp.")
    updated_at: datetime = Field(description="Latest heartbeat timestamp.")
    finished_at: datetime | None = Field(description="Terminal timestamp.")


class ConversationHistory(BaseModel):
    """Detached persisted history and recovery information.

    Attributes:
        scope:
            Complete ownership.
        settings:
            Saved defaults, absent before first configuration or send.
        messages:
            Committed messages in path order.
        attempts:
            All attempts in submission order.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ConversationScope = Field(description="Complete ownership.")
    settings: ConversationSettings | None = Field(description="Saved defaults.")
    messages: tuple[Message, ...] = Field(description="Committed ordered history.")
    attempts: tuple[GenerationAttempt, ...] = Field(description="Attempt provenance.")
