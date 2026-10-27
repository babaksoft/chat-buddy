"""Context selection and structured-delta contracts for Storyline memory."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chat_buddy.characters.domain.continuity import StartingRelationship
from chat_buddy.characters.domain.conversation import ConversationScope
from chat_buddy.characters.domain.errors import (
    InvalidMemoryDeltaTargetError,
    ProtectedMemoryCorrectionError,
)
from chat_buddy.characters.domain.memory import (
    ExtractionProvenance,
    MemoryAuthorship,
    MemoryEvidence,
    MemoryRevisionState,
    ScenePosition,
    StorylineMemory,
)
from chat_buddy.characters.domain.strategy import StrategyIdentity
from chat_buddy.characters.domain.summary import CompletedTurn, SummaryRevision

MAX_DELTA_COMMANDS = 16


class ExtractionBudget(BaseModel):
    """Dedicated positive budget for contextual memory extraction.

    Attributes:
        input_tokens:
            Total tokens available to the selection strategy.
        fixed_overhead_tokens:
            Tokens occupied by prompt framing before context blocks.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int = Field(gt=0, description="Total extraction input capacity.")
    fixed_overhead_tokens: int = Field(ge=0, description="Fixed prompt-framing tokens.")

    @model_validator(mode="after")
    def validate_capacity(self) -> Self:
        """Leave positive capacity for selected context.

        Returns:
            Validated budget.

        Raises:
            ValueError:
                If fixed overhead exhausts the input budget.
        """

        if self.fixed_overhead_tokens >= self.input_tokens:
            raise ValueError("Fixed overhead must leave positive context capacity")
        return self


class MemoryExtractionContext(BaseModel):
    """Immutable eligible inputs before dedicated-budget selection.

    Attributes:
        scope:
            Complete source scene conversation ownership.
        scene:
            Source scene temporal position.
        identity_label:
            Identity label needed for reference resolution.
        persona_label:
            Persona label needed for reference resolution.
        starting_relationship:
            Continuity-owned starting relationship.
        scene_setup:
            Frozen source-scene setup.
        summary:
            Compatible selected-branch summary, when present.
        recent_turns:
            Chronological selected-path turns before the source turn.
        eligible_memories:
            Current branch- and time-eligible Storyline memories.
        source_turn:
            Exact complete selected turn marked as new evidence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    scope: ConversationScope = Field(description="Complete source ownership.")
    scene: ScenePosition = Field(description="Source scene position.")
    identity_label: str = Field(
        min_length=1, max_length=128, description="Identity reference label."
    )
    persona_label: str = Field(
        min_length=1, max_length=128, description="Persona reference label."
    )
    starting_relationship: StartingRelationship = Field(
        description="Continuity starting relationship."
    )
    scene_setup: str = Field(
        min_length=1, max_length=8192, description="Frozen scene setup."
    )
    summary: SummaryRevision | None = Field(
        description="Compatible selected-branch summary."
    )
    recent_turns: tuple[CompletedTurn, ...] = Field(
        description="Chronological selected-path context turns."
    )
    eligible_memories: tuple[StorylineMemory, ...] = Field(
        description="Eligible current logical memories."
    )
    source_turn: CompletedTurn = Field(description="Exact new source evidence.")

    @model_validator(mode="after")
    def validate_ownership_and_order(self) -> Self:
        """Require one scope, current memories, and chronological distinct turns.

        Returns:
            Validated extraction context.

        Raises:
            ValueError:
                If any context block is foreign, ineligible, or unordered.
        """

        turns = (*self.recent_turns, self.source_turn)
        if any(turn.user.scope != self.scope for turn in turns):
            raise ValueError("Extraction turns must belong to the source scope")
        user_sequences = tuple(turn.user.sequence for turn in turns)
        if user_sequences != tuple(sorted(user_sequences)) or len(
            set(user_sequences)
        ) != len(user_sequences):
            raise ValueError("Extraction turns must be unique and chronological")

        if self.summary is not None and self.summary.scope != self.scope:
            raise ValueError("Extraction summary must belong to the source scope")

        if any(
            memory.continuity_id != self.scope.continuity_id
            for memory in self.eligible_memories
        ):
            raise ValueError("Extraction memories must belong to the Storyline")
        if any(
            memory.current.state != MemoryRevisionState.ACTIVE
            or memory.current.source.occurrence.position > self.scene.position
            or memory.current.source.learned.position > self.scene.position
            for memory in self.eligible_memories
        ):
            raise ValueError("Extraction context contains an ineligible memory")
        memory_ids = tuple(memory.id for memory in self.eligible_memories)
        if len(set(memory_ids)) != len(memory_ids):
            raise ValueError("Extraction memories must be unique")

        return self


class MemorySelectionResult(BaseModel):
    """Deterministic whole-record selection supplied to a delta extractor.

    Attributes:
        id:
            Stable selection snapshot identifier.
        selector:
            Selector strategy and version.
        context:
            Complete validated eligible input snapshot.
        included_turn_ids:
            Included recent persona checkpoints in chronological order.
        omitted_turn_ids:
            Omitted recent persona checkpoints in chronological order.
        included_memory_ids:
            Included opaque logical-memory identifiers.
        omitted_memory_ids:
            Omitted eligible logical-memory identifiers.
        summary_included:
            Whether the compatible summary was admitted whole.
        prompt:
            Immutable rendered extraction input blocks.
        token_count:
            Total estimated input tokens including fixed overhead.
        budget:
            Dedicated selection budget.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(description="Stable selection snapshot identifier.")
    selector: StrategyIdentity = Field(description="Selector strategy identity.")
    context: MemoryExtractionContext = Field(description="Eligible source context.")
    included_turn_ids: tuple[UUID, ...] = Field(
        description="Included recent persona checkpoints."
    )
    omitted_turn_ids: tuple[UUID, ...] = Field(
        description="Omitted recent persona checkpoints."
    )
    included_memory_ids: tuple[UUID, ...] = Field(
        description="Included eligible memory identifiers."
    )
    omitted_memory_ids: tuple[UUID, ...] = Field(
        description="Omitted eligible memory identifiers."
    )
    summary_included: bool = Field(description="Whether summary was admitted.")
    prompt: tuple[str, ...] = Field(
        min_length=1, description="Ordered rendered extraction blocks."
    )
    token_count: int = Field(gt=0, description="Estimated input token count.")
    budget: ExtractionBudget = Field(description="Dedicated extraction budget.")

    @model_validator(mode="after")
    def validate_partition(self) -> Self:
        """Require exact unique context partitions and a bounded prompt.

        Returns:
            Validated selection snapshot.

        Raises:
            ValueError:
                If selection accounting omits, duplicates, or invents records.
        """

        turn_ids = tuple(turn.persona.id for turn in self.context.recent_turns)
        memory_ids = tuple(memory.id for memory in self.context.eligible_memories)
        if not _is_partition(turn_ids, self.included_turn_ids, self.omitted_turn_ids):
            raise ValueError("Selected and omitted turns must partition context")
        if not _is_partition(
            memory_ids, self.included_memory_ids, self.omitted_memory_ids
        ):
            raise ValueError("Selected and omitted memories must partition context")
        if self.summary_included and self.context.summary is None:
            raise ValueError("A missing summary cannot be included")
        if self.token_count > self.budget.input_tokens:
            raise ValueError("Extraction selection exceeds its input budget")
        return self

    def validate_delta(self, delta: MemoryDelta) -> None:
        """Reject omitted targets and protected automatic supersedes.

        Args:
            delta:
                Structured extractor proposal to inspect.

        Raises:
            InvalidMemoryDeltaTargetError:
                If ownership, source, or opaque target is not in this snapshot.
            ProtectedMemoryCorrectionError:
                If extraction would supersede user-authored content.
        """

        if (
            delta.selection_id != self.id
            or delta.scope != self.context.scope
            or delta.source_persona_message_id != self.context.source_turn.persona.id
        ):
            raise InvalidMemoryDeltaTargetError(
                "Delta does not belong to the extraction selection"
            )
        included = {
            memory.id: memory
            for memory in self.context.eligible_memories
            if memory.id in self.included_memory_ids
        }
        for command in delta.commands:
            if command.operation in {"reinforce", "supersede"}:
                target = included.get(command.target_memory_id)
                if target is None or target.current.id != command.expected_revision_id:
                    raise InvalidMemoryDeltaTargetError(
                        "Delta target is omitted, foreign, or stale"
                    )
                if command.operation == "supersede" and (
                    target.current.authorship == MemoryAuthorship.USER
                ):
                    raise ProtectedMemoryCorrectionError(
                        "Automatic extraction cannot supersede user content"
                    )
            elif command.operation == "conflict" and command.target_memory_id:
                target = included.get(command.target_memory_id)
                if target is None or target.current.id != command.expected_revision_id:
                    raise InvalidMemoryDeltaTargetError(
                        "Conflict target is omitted, foreign, or stale"
                    )


class CreateMemoryCommand(BaseModel):
    """Proposal to create one logical memory from the new source turn.

    Attributes:
        operation:
            Discriminator for a create operation.
        subject:
            Proposed normalized subject.
        content:
            Proposed remembered assertion.
        occurrence:
            Supplied scene position where the assertion occurred.
        evidence:
            Exact new source evidence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    operation: Literal["create"] = Field(
        default="create", description="Command operation."
    )
    subject: str = Field(
        min_length=1, max_length=256, description="Proposed normalized subject."
    )
    content: str = Field(
        min_length=1, max_length=4096, description="Proposed assertion."
    )
    occurrence: ScenePosition = Field(description="Asserted temporal position.")
    evidence: MemoryEvidence = Field(description="Exact new source evidence.")


class ReinforceMemoryCommand(BaseModel):
    """Proposal to add distinct evidence to unchanged current content.

    Attributes:
        operation:
            Discriminator for a reinforcement.
        target_memory_id:
            Opaque included logical-memory identifier.
        expected_revision_id:
            Included current revision observed by the extractor.
        content:
            Unchanged content used for application validation.
        evidence:
            Exact new source evidence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: Literal["reinforce"] = Field(
        default="reinforce", description="Command operation."
    )
    target_memory_id: UUID = Field(description="Opaque target memory identifier.")
    expected_revision_id: UUID = Field(description="Observed current revision.")
    content: str = Field(
        min_length=1, max_length=4096, description="Unchanged target content."
    )
    evidence: MemoryEvidence = Field(description="Exact new source evidence.")


class SupersedeMemoryCommand(BaseModel):
    """Proposal to supersede active extracted content.

    Attributes:
        operation:
            Discriminator for a supersede operation.
        target_memory_id:
            Opaque included logical-memory identifier.
        expected_revision_id:
            Included current revision observed by the extractor.
        subject:
            Proposed replacement subject.
        content:
            Proposed replacement assertion.
        occurrence:
            Supplied scene position where the assertion occurred.
        evidence:
            Exact new source evidence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    operation: Literal["supersede"] = Field(
        default="supersede", description="Command operation."
    )
    target_memory_id: UUID = Field(description="Opaque target memory identifier.")
    expected_revision_id: UUID = Field(description="Observed current revision.")
    subject: str = Field(
        min_length=1, max_length=256, description="Replacement normalized subject."
    )
    content: str = Field(
        min_length=1, max_length=4096, description="Replacement assertion."
    )
    occurrence: ScenePosition = Field(description="Asserted temporal position.")
    evidence: MemoryEvidence = Field(description="Exact new source evidence.")


class RecordMemoryConflictCommand(BaseModel):
    """Proposal to record ambiguity without changing current memory.

    Attributes:
        operation:
            Discriminator for a conflict operation.
        target_memory_id:
            Opaque included target, when one is known.
        expected_revision_id:
            Included current revision paired with a target.
        subject:
            Proposed conflicting subject.
        content:
            Proposed conflicting assertion.
        occurrence:
            Supplied scene position where the assertion occurred.
        evidence:
            Exact new source evidence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    operation: Literal["conflict"] = Field(
        default="conflict", description="Command operation."
    )
    target_memory_id: UUID | None = Field(description="Optional opaque target.")
    expected_revision_id: UUID | None = Field(
        description="Observed revision for the optional target."
    )
    subject: str = Field(
        min_length=1, max_length=256, description="Conflicting normalized subject."
    )
    content: str = Field(
        min_length=1, max_length=4096, description="Conflicting assertion."
    )
    occurrence: ScenePosition = Field(description="Asserted temporal position.")
    evidence: MemoryEvidence = Field(description="Exact new source evidence.")

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        """Pair a conflict target with its observed revision.

        Returns:
            Validated conflict operation.

        Raises:
            ValueError:
                If only one target reference is supplied.
        """

        if (self.target_memory_id is None) != (self.expected_revision_id is None):
            raise ValueError("Conflict target and revision must be paired")
        return self


class NoMemoryChangeCommand(BaseModel):
    """Explicit assertion that the source turn produces no memory change.

    Attributes:
        operation:
            Discriminator for the no-change result.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: Literal["no_change"] = Field(
        default="no_change", description="Command operation."
    )


MemoryDeltaCommand = Annotated[
    CreateMemoryCommand
    | ReinforceMemoryCommand
    | SupersedeMemoryCommand
    | RecordMemoryConflictCommand
    | NoMemoryChangeCommand,
    Field(discriminator="operation"),
]


class MemoryDelta(BaseModel):
    """Bounded atomic structured proposal from one contextual extraction.

    Attributes:
        selection_id:
            Exact immutable selection snapshot used by the extractor.
        scope:
            Complete source conversation ownership.
        source_persona_message_id:
            Exact new-evidence persona checkpoint.
        extractor:
            Delta-extraction strategy and version.
        operations:
            No-change alone or a bounded non-empty operation set.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    selection_id: UUID = Field(description="Source selection snapshot.")
    scope: ConversationScope = Field(description="Complete source ownership.")
    source_persona_message_id: UUID = Field(
        description="Exact new-evidence persona checkpoint."
    )
    extractor: StrategyIdentity = Field(description="Extractor strategy identity.")
    commands: tuple[MemoryDeltaCommand, ...] = Field(
        min_length=1,
        max_length=MAX_DELTA_COMMANDS,
        description="Bounded atomic delta commands.",
    )

    @model_validator(mode="after")
    def validate_operations(self) -> Self:
        """Reject mixed no-change, duplicate targets, and competing subjects.

        Returns:
            Validated atomic delta.

        Raises:
            ValueError:
                If operations are contradictory or cite a different source.
        """

        if any(command.operation == "no_change" for command in self.commands):
            if len(self.commands) != 1:
                raise ValueError("No-change must be the only delta command")
            return self

        targets = [
            command.target_memory_id
            for command in self.commands
            if command.operation in {"reinforce", "supersede", "conflict"}
            and command.target_memory_id is not None
        ]
        if len(set(targets)) != len(targets):
            raise ValueError("A delta cannot operate twice on one memory lineage")

        subjects = [
            command.subject.casefold()
            for command in self.commands
            if command.operation in {"create", "supersede", "conflict"}
        ]
        if len(set(subjects)) != len(subjects):
            raise ValueError("A delta cannot propose competing normalized subjects")

        for command in self.commands:
            if command.operation == "no_change":
                continue
            evidence = command.evidence
            if (
                evidence.scope != self.scope
                or evidence.persona_message_id != self.source_persona_message_id
            ):
                raise ValueError("Every command must cite the exact source turn")
            if command.operation in {"create", "supersede", "conflict"} and (
                command.occurrence != evidence.occurrence
            ):
                raise ValueError("Command occurrence must match source evidence")
        return self


class MemoryContextSelector(Protocol):
    """Versioned strategy for deterministic whole-record context selection."""

    @property
    def strategy_id(self) -> StrategyIdentity:
        """Return the selector name and behavior version.

        Returns:
            Stable selector identity.
        """

        ...

    def select(
        self, context: MemoryExtractionContext, budget: ExtractionBudget
    ) -> MemorySelectionResult:
        """Select and render an immutable bounded extraction snapshot.

        Args:
            context:
                Complete eligible inputs.
            budget:
                Dedicated extraction input capacity.

        Returns:
            Deterministic whole-record selection.
        """

        ...


class MemoryDeltaExtractor(Protocol):
    """Versioned strategy that proposes deltas without persistence authority."""

    @property
    def strategy_id(self) -> StrategyIdentity:
        """Return the extractor name and behavior version.

        Returns:
            Stable extractor identity.
        """

        ...

    def extract(self, selection: MemorySelectionResult) -> MemoryDelta:
        """Propose a structured delta from one immutable selection.

        Args:
            selection:
                Bounded contextual snapshot.

        Returns:
            Detached delta carrying no write authority.
        """

        ...

    def provenance(self, selection: MemorySelectionResult) -> ExtractionProvenance:
        """Describe the exact extraction configuration for a selection.

        Args:
            selection:
                Immutable snapshot whose selector completes the provenance.

        Returns:
            Complete non-secret extraction provenance.
        """

        ...


def _is_partition(
    eligible: tuple[UUID, ...], included: tuple[UUID, ...], omitted: tuple[UUID, ...]
) -> bool:
    """Return whether included and omitted are a unique exact partition.

    Args:
        eligible:
            Complete eligible identifier sequence.
        included:
            Selected identifier sequence.
        omitted:
            Omitted identifier sequence.

    Returns:
        Whether both sequences partition eligible identifiers exactly.
    """

    combined = (*included, *omitted)
    return len(set(combined)) == len(combined) and set(combined) == set(eligible)
