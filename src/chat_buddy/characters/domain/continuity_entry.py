"""Immutable shared ownership and position values for continuity entries."""

from __future__ import annotations

from functools import total_ordering
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chat_buddy.characters.domain.continuity import ContinuityMode
from chat_buddy.characters.domain.conversation import ConversationScope


@total_ordering
class EntryPosition(BaseModel):
    """Comparable position of one Entry within a narrative continuity.

    Attributes:
        entry_id:
            Stable Entry identifier at this position.
        continuity_id:
            Continuity in which the position is meaningful.
        mode:
            Storyline or Timeline mode of the Entry.
        position:
            Positive immutable order within the continuity.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entry_id: UUID = Field(description="Stable Entry identifier.")
    continuity_id: UUID = Field(description="Owning continuity identifier.")
    mode: ContinuityMode = Field(description="Narrative continuity mode.")
    position: int = Field(ge=1, strict=True, description="Immutable Entry order.")

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        """Reject Ongoing positions because Ongoing has no Entry.

        Returns:
            The validated immutable position.

        Raises:
            ValueError:
                If the position claims Ongoing mode.
        """

        if self.mode == ContinuityMode.ONGOING:
            raise ValueError("Ongoing continuities do not have Entry positions")
        return self

    def __lt__(self, other: object) -> bool:
        """Compare positions only inside the same continuity and mode.

        Args:
            other:
                Candidate Entry position.

        Returns:
            Whether this position precedes the other position.

        Raises:
            TypeError:
                If the other value is not an Entry position.
            ValueError:
                If the positions do not share one continuity and mode.
        """

        if not isinstance(other, EntryPosition):
            raise TypeError("Entry positions can be compared only to each other")
        self._require_comparable(other)
        return self.position < other.position

    def _require_comparable(self, other: EntryPosition) -> None:
        """Require shared continuity and mode before ordering positions.

        Args:
            other:
                Other position being compared.

        Raises:
            ValueError:
                If continuity or mode differs.
        """

        if self.continuity_id != other.continuity_id or self.mode != other.mode:
            raise ValueError(
                "Entry positions are comparable only within one continuity and mode"
            )


class ContinuityEntry(BaseModel):
    """Shared immutable owner represented by a Scene or Timeline Day.

    Attributes:
        id:
            Stable Entry identifier.
        continuity_id:
            Permanent owning continuity.
        identity_id:
            Permanent identity owner.
        persona_id:
            Permanent persona owner.
        conversation_id:
            Exact conversation owned by the Entry.
        mode:
            Permanent Storyline or Timeline mode.
        position:
            Positive immutable order within the continuity.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(description="Stable Entry identifier.")
    continuity_id: UUID = Field(description="Permanent owning continuity.")
    identity_id: UUID = Field(description="Permanent identity owner.")
    persona_id: UUID = Field(description="Permanent persona owner.")
    conversation_id: UUID = Field(description="Exact owned conversation.")
    mode: ContinuityMode = Field(description="Permanent narrative mode.")
    position: int = Field(ge=1, strict=True, description="Immutable Entry order.")

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        """Reject Ongoing ownership because Ongoing has no Entry.

        Returns:
            The validated immutable Entry.

        Raises:
            ValueError:
                If the Entry claims Ongoing mode.
        """

        if self.mode == ContinuityMode.ONGOING:
            raise ValueError("Ongoing continuities do not have Entries")
        return self

    @property
    def scope(self) -> ConversationScope:
        """Return complete conversation ownership derived from the Entry.

        Returns:
            Immutable conversation scope.
        """

        return ConversationScope(
            identity_id=self.identity_id,
            persona_id=self.persona_id,
            continuity_id=self.continuity_id,
            conversation_id=self.conversation_id,
        )

    @property
    def entry_position(self) -> EntryPosition:
        """Return the Entry's shared temporal value.

        Returns:
            Immutable Entry position.
        """

        return EntryPosition(
            entry_id=self.id,
            continuity_id=self.continuity_id,
            mode=self.mode,
            position=self.position,
        )
