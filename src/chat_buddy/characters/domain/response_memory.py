"""Versioned whole-record selection for Storyline response memory."""

from __future__ import annotations

from typing import Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chat_buddy.characters.domain.llm import TokenCounter
from chat_buddy.characters.domain.memory import StorylineMemory
from chat_buddy.characters.domain.strategy import StrategyIdentity


class ResponseMemoryBudget(BaseModel):
    """Dedicated capacity for optional Storyline response memories.

    Attributes:
        input_tokens:
            Maximum tokens occupied by complete rendered memory blocks.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int = Field(gt=0, description="Maximum response-memory input tokens.")


class ResponseMemorySelection(BaseModel):
    """One deterministic response-memory selection result.

    Attributes:
        selector:
            Independently versioned response-memory strategy.
        eligible_memory_ids:
            Complete ordered candidate identifiers.
        included_memories:
            Complete records admitted within the dedicated budget.
        omitted_memory_ids:
            Eligible identifiers omitted by the selector.
        token_count:
            Exact token count for the included rendered memory blocks.
        budget:
            Dedicated response-memory capacity used for selection.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    selector: StrategyIdentity = Field(description="Response selector identity.")
    eligible_memory_ids: tuple[UUID, ...] = Field(
        description="Ordered eligible memory identifiers."
    )
    included_memories: tuple[StorylineMemory, ...] = Field(
        description="Included complete memory records."
    )
    omitted_memory_ids: tuple[UUID, ...] = Field(
        description="Omitted eligible memory identifiers."
    )
    token_count: int = Field(
        ge=0, description="Tokens occupied by included memory blocks."
    )
    budget: ResponseMemoryBudget = Field(description="Dedicated selection budget.")

    @model_validator(mode="after")
    def validate_partition(self) -> Self:
        """Require a unique exact partition bounded by the dedicated budget.

        Returns:
            Validated immutable selection.

        Raises:
            ValueError:
                If identifiers are duplicated, invented, omitted, or over budget.
        """

        included_ids = tuple(memory.id for memory in self.included_memories)
        if len(set(self.eligible_memory_ids)) != len(self.eligible_memory_ids):
            raise ValueError("Eligible response memories must be unique")
        if set(included_ids).intersection(self.omitted_memory_ids):
            raise ValueError("Included and omitted response memories must be disjoint")
        if {*included_ids, *self.omitted_memory_ids} != set(self.eligible_memory_ids):
            raise ValueError("Response selection must partition eligible memories")
        if len(included_ids) + len(self.omitted_memory_ids) != len(
            self.eligible_memory_ids
        ):
            raise ValueError("Response selection must not duplicate memories")
        if self.token_count > self.budget.input_tokens:
            raise ValueError("Response-memory selection exceeds its budget")
        return self


class ResponseMemorySelector(Protocol):
    """Select complete eligible memories under an independent response budget."""

    @property
    def strategy_id(self) -> StrategyIdentity:
        """Return the stable strategy name and behavior version.

        Returns:
            Response-memory selector identity.
        """

        ...

    def select(
        self,
        memories: tuple[StorylineMemory, ...],
        budget: ResponseMemoryBudget,
        counter: TokenCounter,
    ) -> ResponseMemorySelection:
        """Select deterministic complete memory records.

        Args:
            memories:
                Branch- and time-eligible Storyline memories.
            budget:
                Dedicated response-memory capacity.
            counter:
                Provider-specific token counter.

        Returns:
            Complete selection and omission accounting.
        """

        ...
