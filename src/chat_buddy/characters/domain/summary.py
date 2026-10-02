"""Immutable rolling-summary and context-selection values."""

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chat_buddy.characters.domain.conversation import ConversationScope, Message
from chat_buddy.characters.domain.llm import EffectiveGeneration, PromptMessage


class CompletedTurn(BaseModel):
    """One complete, indivisible Ongoing exchange.

    Attributes:
        user:
            Committed user message.
        persona:
            Committed persona response.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    user: Message = Field(description="Committed user input.")
    persona: Message = Field(description="Committed persona response.")

    @model_validator(mode="after")
    def validate_pair(self) -> Self:
        """Require adjacent messages with identical ownership.

        Returns:
            Validated complete turn.

        Raises:
            ValueError:
                If the messages do not form one owned adjacent turn.
        """

        if (
            self.user.role != "user"
            or self.persona.role != "persona"
            or self.user.scope != self.persona.scope
            or self.persona.sequence != self.user.sequence + 1
        ):
            raise ValueError("Messages do not form one complete owned turn.")
        return self


class SummaryRevision(BaseModel):
    """One immutable durable summary version.

    Attributes:
        id:
            Stable revision identifier.
        scope:
            Complete continuity and conversation ownership.
        revision:
            Positive lineage position.
        predecessor_id:
            Prior revision, absent on the first version.
        checkpoint_message_id:
            Last covered persona message.
        checkpoint_sequence:
            Even path position of the checkpoint.
        content:
            Nonblank generated summary.
        generation:
            Effective summary provider and model provenance.
        is_active:
            Whether this is the sole active revision.
        created_at:
            UTC creation timestamp.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(description="Stable revision identifier.")
    scope: ConversationScope = Field(description="Complete ownership.")
    revision: int = Field(gt=0, description="Monotonic lineage revision.")
    predecessor_id: UUID | None = Field(description="Prior revision identifier.")
    checkpoint_message_id: UUID = Field(description="Last covered persona message.")
    checkpoint_sequence: int = Field(gt=0, description="Covered path position.")
    content: str = Field(min_length=1, pattern=r"\S", description="Summary text.")
    generation: EffectiveGeneration = Field(description="Generation provenance.")
    is_active: bool = Field(description="Sole active-version designation.")
    created_at: datetime = Field(description="UTC creation timestamp.")

    @model_validator(mode="after")
    def validate_lineage(self) -> Self:
        """Require summary capability, even checkpoints, and predecessor shape.

        Returns:
            Validated immutable revision.

        Raises:
            ValueError:
                If provenance contradicts the revision.
        """

        if self.generation.capability != "summary":
            raise ValueError("Summary provenance requires summary generation.")
        if self.checkpoint_sequence % 2 != 0:
            raise ValueError("Summary checkpoints must be persona messages.")
        if (self.revision == 1) != (self.predecessor_id is None):
            raise ValueError("Summary predecessor must match its revision.")
        return self


class EligibleContext(BaseModel):
    """Scoped response inputs after checkpoint eligibility.

    Attributes:
        summary:
            Active durable summary when present.
        uncovered_turns:
            Complete chronological turns after its checkpoint.
        current_input:
            Persisted unmatched input or uncommitted submitted text.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: SummaryRevision | None = Field(description="Active summary.")
    uncovered_turns: tuple[CompletedTurn, ...] = Field(
        description="Chronological uncovered complete turns."
    )
    current_input: str | None = Field(description="Current user input.")


class ContextSelection(BaseModel):
    """One deterministic budget decision.

    Attributes:
        prompt:
            Provider-ready bounded response prompt.
        included_turns:
            Chronological uncovered suffix included verbatim.
        omitted_turns:
            Chronological uncovered prefix requiring compression.
        tokens:
            Count before the fixed overhead reserve.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: tuple[PromptMessage, ...] = Field(description="Bounded response prompt.")
    included_turns: tuple[CompletedTurn, ...] = Field(
        description="Included chronological suffix."
    )
    omitted_turns: tuple[CompletedTurn, ...] = Field(
        description="Oldest prefix requiring compression."
    )
    tokens: int = Field(ge=0, description="Estimated prompt tokens.")
