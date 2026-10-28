"""Immutable Storyline memory lifecycle and management contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from chat_buddy.characters.domain.conversation import ConversationScope
from chat_buddy.characters.domain.errors import (
    ExtractionEffectConflictError,
    MemoryConflictNotFoundError,
    StaleMemoryConflictError,
)
from chat_buddy.characters.domain.llm import GenerationConfiguration
from chat_buddy.characters.domain.strategy import StrategyIdentity
from chat_buddy.characters.domain.validation import SEMANTIC_VERSION_PATTERN


class MemoryRevisionState(StrEnum):
    """Lifecycle state of one immutable memory revision."""

    ACTIVE = "active"
    EXCLUDED = "excluded"
    SUPERSEDED = "superseded"


class MemoryAuthorship(StrEnum):
    """Authority responsible for the content of a memory revision."""

    EXTRACTED = "extracted"
    USER = "user"


class MemoryRevisionKind(StrEnum):
    """Reason an immutable memory revision entered its lineage."""

    EXTRACTION = "extraction"
    AUTOMATIC_SUPERSEDE = "automatic_supersede"
    USER_CORRECTION = "user_correction"
    EXCLUSION = "exclusion"
    REACTIVATION = "reactivation"


class MemoryConflictState(StrEnum):
    """Lifecycle state of an extraction conflict."""

    UNRESOLVED = "unresolved"
    DISMISSED = "dismissed"


class ExtractionEffectState(StrEnum):
    """Reservation and terminal states of one extraction effect."""

    RESERVED = "reserved"
    NO_CHANGE = "no_change"
    APPLIED = "applied"


class ScenePosition(BaseModel):
    """Immutable temporal position inside one Storyline.

    Attributes:
        scene_id:
            Scene occupying the position.
        position:
            Positive append-only scene ordinal.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scene_id: UUID = Field(description="Scene identifier.")
    position: int = Field(gt=0, description="Append-only scene ordinal.")


class ExtractionProvenance(BaseModel):
    """Reproducible non-secret configuration for a memory extraction.

    Attributes:
        selector:
            Context-selection strategy and version.
        extractor:
            Delta-extraction strategy and version.
        prompt_schema_version:
            Version of the structured extraction prompt.
        provider:
            Provider key used for extraction.
        model:
            Provider-local model name.
        configuration:
            Effective non-secret generation configuration.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    selector: StrategyIdentity = Field(description="Selector strategy identity.")
    extractor: StrategyIdentity = Field(description="Extractor strategy identity.")
    prompt_schema_version: str = Field(
        min_length=1,
        max_length=64,
        pattern=SEMANTIC_VERSION_PATTERN,
        description="Structured prompt schema version.",
    )
    provider: str = Field(min_length=1, max_length=64, description="Provider key.")
    model: str = Field(min_length=1, max_length=256, description="Model name.")
    configuration: GenerationConfiguration = Field(
        description="Effective non-secret generation configuration."
    )


class MemoryEvidence(BaseModel):
    """Exact complete selected turn supporting a memory interpretation.

    Attributes:
        id:
            Stable evidence-link identifier.
        scope:
            Complete source conversation ownership.
        scene_id:
            Source scene identifier.
        user_message_id:
            Source user-message identifier.
        persona_message_id:
            Adjacent source persona-message identifier and checkpoint.
        persona_checkpoint:
            Even selected-path position of the persona message.
        occurrence:
            Scene where the asserted event or state occurred.
        learned:
            Source scene where the persona learned the assertion.
        extraction:
            Exact extraction strategy and model configuration.
        created_at:
            UTC evidence-link creation time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(description="Stable evidence-link identifier.")
    scope: ConversationScope = Field(description="Complete source ownership.")
    scene_id: UUID = Field(description="Source scene identifier.")
    user_message_id: UUID = Field(description="Source user-message identifier.")
    persona_message_id: UUID = Field(description="Source persona-message checkpoint.")
    persona_checkpoint: int = Field(
        gt=0, description="Even selected-path persona-message position."
    )
    occurrence: ScenePosition = Field(description="Asserted temporal position.")
    learned: ScenePosition = Field(description="Learning temporal position.")
    extraction: ExtractionProvenance = Field(
        description="Extraction configuration provenance."
    )
    created_at: AwareDatetime = Field(description="UTC creation time.")

    @model_validator(mode="after")
    def validate_temporal_provenance(self) -> Self:
        """Require an even source checkpoint and ordered source positions.

        Returns:
            Validated evidence.

        Raises:
            ValueError:
                If source or temporal provenance is contradictory.
        """

        if self.persona_checkpoint % 2 != 0:
            raise ValueError("Memory evidence checkpoints must be persona messages")
        if self.learned.scene_id != self.scene_id:
            raise ValueError("Learned position must identify the source scene")
        if self.occurrence.position > self.learned.position:
            raise ValueError("Occurrence cannot be later than learning")
        return self


class MemoryRevision(BaseModel):
    """One immutable revision in a logical Storyline memory lineage.

    Attributes:
        id:
            Stable revision identifier.
        memory_id:
            Stable logical-memory identifier.
        continuity_id:
            Owning Storyline identifier.
        revision:
            Positive consecutive lineage position.
        predecessor_id:
            Immediately preceding revision identifier.
        subject:
            User-readable normalized fact subject.
        content:
            Complete remembered assertion.
        state:
            Active, excluded, or superseded lifecycle state.
        authorship:
            Extractor or user authority over content.
        kind:
            Lifecycle operation that created the revision.
        source:
            Originating evidence retained through management transitions.
        created_at:
            UTC revision creation time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(description="Stable revision identifier.")
    memory_id: UUID = Field(description="Stable logical-memory identifier.")
    continuity_id: UUID = Field(description="Owning Storyline identifier.")
    revision: int = Field(gt=0, description="Consecutive lineage position.")
    predecessor_id: UUID | None = Field(description="Previous revision identifier.")
    subject: str = Field(
        min_length=1, max_length=256, description="Normalized fact subject."
    )
    content: str = Field(
        min_length=1, max_length=4096, description="Remembered assertion."
    )
    state: MemoryRevisionState = Field(description="Revision lifecycle state.")
    authorship: MemoryAuthorship = Field(description="Content authority.")
    kind: MemoryRevisionKind = Field(description="Revision creation operation.")
    source: MemoryEvidence = Field(description="Originating source evidence.")
    created_at: AwareDatetime = Field(description="UTC revision creation time.")

    @model_validator(mode="after")
    def validate_revision_origin(self) -> Self:
        """Keep lineage shape and evidence inside the owning Storyline.

        Returns:
            Validated revision.

        Raises:
            ValueError:
                If predecessor or ownership provenance is contradictory.
        """

        if (self.revision == 1) != (self.predecessor_id is None):
            raise ValueError("Memory predecessor must match its revision")

        if self.source.scope.continuity_id != self.continuity_id:
            raise ValueError("Memory evidence must belong to the owning Storyline")

        if self.revision == 1 and (
            self.kind != MemoryRevisionKind.EXTRACTION
            or self.authorship != MemoryAuthorship.EXTRACTED
            or self.state == MemoryRevisionState.EXCLUDED
        ):
            raise ValueError("The first memory revision must originate by extraction")
        if self.revision > 1 and self.kind == MemoryRevisionKind.EXTRACTION:
            raise ValueError("Only the first memory revision may be extraction")

        return self


class StorylineMemory(BaseModel):
    """A logical memory with its complete immutable revision and evidence history.

    Attributes:
        id:
            Stable logical-memory identifier.
        continuity_id:
            Owning Storyline identifier.
        current_revision_id:
            Sole current active or excluded revision.
        revisions:
            Complete consecutive revision lineage.
        evidence:
            Distinct origin and reinforcement evidence links.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(description="Stable logical-memory identifier.")
    continuity_id: UUID = Field(description="Owning Storyline identifier.")
    current_revision_id: UUID = Field(description="Current revision identifier.")
    revisions: tuple[MemoryRevision, ...] = Field(
        min_length=1, description="Complete immutable revision lineage."
    )
    evidence: tuple[MemoryEvidence, ...] = Field(
        min_length=1, description="Distinct supporting evidence links."
    )

    @property
    def current(self) -> MemoryRevision:
        """Return the validated current revision.

        Returns:
            Sole current active or excluded revision.
        """

        return self.revisions[-1]

    @model_validator(mode="after")
    def validate_lineage(self) -> Self:
        """Require one owned consecutive lineage and distinct owned evidence.

        Returns:
            Validated logical memory.

        Raises:
            ValueError:
                If lineage, lifecycle, or provenance is inconsistent.
        """

        if any(
            revision.memory_id != self.id
            or revision.continuity_id != self.continuity_id
            for revision in self.revisions
        ):
            raise ValueError("Every revision must belong to the logical memory")

        if tuple(revision.revision for revision in self.revisions) != tuple(
            range(1, len(self.revisions) + 1)
        ):
            raise ValueError("Memory revisions must be consecutive")

        for previous, current in zip(self.revisions, self.revisions[1:]):
            if current.predecessor_id != previous.id:
                raise ValueError("Memory revision predecessors must be consecutive")

            same_interpretation = (
                current.subject == previous.subject
                and current.content == previous.content
                and current.authorship == previous.authorship
                and current.source == previous.source
            )
            if (
                current.kind
                in {
                    MemoryRevisionKind.EXCLUSION,
                    MemoryRevisionKind.REACTIVATION,
                }
                and not same_interpretation
            ):
                raise ValueError(
                    "Exclusion and reactivation must retain memory interpretation"
                )

            if current.kind == MemoryRevisionKind.EXCLUSION and (
                current.state == MemoryRevisionState.ACTIVE
            ):
                raise ValueError("Exclusion cannot create an active revision")
            if current.kind == MemoryRevisionKind.REACTIVATION and (
                previous.kind != MemoryRevisionKind.EXCLUSION
                or current.state == MemoryRevisionState.EXCLUDED
            ):
                raise ValueError("Reactivation must follow an excluded revision")
            if current.kind == MemoryRevisionKind.USER_CORRECTION and (
                previous.kind == MemoryRevisionKind.EXCLUSION
                or current.authorship != MemoryAuthorship.USER
                or current.state == MemoryRevisionState.EXCLUDED
            ):
                raise ValueError("User correction requires an active predecessor")
            if current.kind == MemoryRevisionKind.AUTOMATIC_SUPERSEDE and (
                previous.kind == MemoryRevisionKind.EXCLUSION
                or previous.authorship != MemoryAuthorship.EXTRACTED
                or current.authorship != MemoryAuthorship.EXTRACTED
                or current.state == MemoryRevisionState.EXCLUDED
            ):
                raise ValueError(
                    "Automatic supersede requires active extracted content"
                )

        if self.current_revision_id != self.revisions[-1].id:
            raise ValueError("Current revision must be the final lineage revision")
        if (
            any(
                revision.state != MemoryRevisionState.SUPERSEDED
                for revision in self.revisions[:-1]
            )
            or self.current.state == MemoryRevisionState.SUPERSEDED
        ):
            raise ValueError("Exactly the final revision must be current")

        if (self.current.kind == MemoryRevisionKind.EXCLUSION) != (
            self.current.state == MemoryRevisionState.EXCLUDED
        ):
            raise ValueError(
                "Current lifecycle state must match its revision operation"
            )

        if any(
            item.scope.continuity_id != self.continuity_id for item in self.evidence
        ):
            raise ValueError("Every evidence link must belong to the Storyline")

        if self.current.source.id not in {item.id for item in self.evidence}:
            raise ValueError("Current source must be retained as supporting evidence")

        persona_messages = tuple(item.persona_message_id for item in self.evidence)
        if len(set(persona_messages)) != len(persona_messages):
            raise ValueError("A source turn can support a memory only once")

        return self


class CorrectMemoryCommand(BaseModel):
    """User-authored correction guarded by the current revision.

    Attributes:
        operation:
            Discriminator for a correction command.
        continuity_id:
            Owning Storyline identifier.
        memory_id:
            Logical memory to correct.
        expected_revision_id:
            Last observed active revision.
        subject:
            Corrected normalized subject.
        content:
            Corrected assertion.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    operation: Literal["correct"] = Field(
        default="correct", description="Management operation."
    )
    continuity_id: UUID = Field(description="Owning Storyline identifier.")
    memory_id: UUID = Field(description="Logical memory identifier.")
    expected_revision_id: UUID = Field(description="Expected active revision.")
    subject: str = Field(
        min_length=1, max_length=256, description="Corrected normalized subject."
    )
    content: str = Field(
        min_length=1, max_length=4096, description="Corrected assertion."
    )


class ChangeMemoryStateCommand(BaseModel):
    """Guarded exclusion or reactivation request.

    Attributes:
        operation:
            Requested lifecycle transition.
        continuity_id:
            Owning Storyline identifier.
        memory_id:
            Logical memory to transition.
        expected_revision_id:
            Last observed current revision.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: Literal["exclude", "reactivate"] = Field(
        description="Requested lifecycle transition."
    )
    continuity_id: UUID = Field(description="Owning Storyline identifier.")
    memory_id: UUID = Field(description="Logical memory identifier.")
    expected_revision_id: UUID = Field(description="Expected current revision.")


class DeleteMemoryCommand(BaseModel):
    """Guarded hard deletion of a complete logical-memory lineage.

    Attributes:
        operation:
            Discriminator for hard deletion.
        continuity_id:
            Owning Storyline identifier.
        memory_id:
            Logical memory to delete.
        expected_revision_id:
            Last observed current revision.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: Literal["delete"] = Field(
        default="delete", description="Management operation."
    )
    continuity_id: UUID = Field(description="Owning Storyline identifier.")
    memory_id: UUID = Field(description="Logical memory identifier.")
    expected_revision_id: UUID = Field(description="Expected current revision.")


class DismissMemoryConflictCommand(BaseModel):
    """Guarded dismissal of one unresolved extraction conflict.

    Attributes:
        operation:
            Discriminator for conflict dismissal.
        continuity_id:
            Owning Storyline identifier.
        conflict_id:
            Conflict to dismiss.
        expected_revision_id:
            Target revision observed with a targeted conflict, otherwise absent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: Literal["dismiss_conflict"] = Field(
        default="dismiss_conflict", description="Management operation."
    )
    continuity_id: UUID = Field(description="Owning Storyline identifier.")
    conflict_id: UUID = Field(description="Conflict identifier.")
    expected_revision_id: UUID | None = Field(
        description="Observed target revision for a targeted conflict."
    )


MemoryManagementCommand = Annotated[
    CorrectMemoryCommand
    | ChangeMemoryStateCommand
    | DeleteMemoryCommand
    | DismissMemoryConflictCommand,
    Field(discriminator="operation"),
]


class MemoryConflict(BaseModel):
    """A proposed contradiction that never changes prompt-eligible memory.

    Attributes:
        id:
            Stable conflict identifier.
        continuity_id:
            Owning Storyline identifier.
        memory_id:
            Target memory when the proposal conflicts with one.
        observed_revision_id:
            Current target revision observed during validation.
        proposed_subject:
            Proposed normalized subject.
        proposed_content:
            Proposed conflicting assertion.
        evidence:
            Exact new source turn.
        state:
            Unresolved or dismissed state.
        created_at:
            UTC conflict creation time.
        dismissed_at:
            UTC dismissal time when dismissed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(description="Stable conflict identifier.")
    continuity_id: UUID = Field(description="Owning Storyline identifier.")
    memory_id: UUID | None = Field(description="Target logical memory, when known.")
    observed_revision_id: UUID | None = Field(
        description="Observed target revision, when targeted."
    )
    proposed_subject: str = Field(
        min_length=1, max_length=256, description="Proposed normalized subject."
    )
    proposed_content: str = Field(
        min_length=1, max_length=4096, description="Proposed conflicting assertion."
    )
    evidence: MemoryEvidence = Field(description="Exact new source evidence.")
    state: MemoryConflictState = Field(description="Conflict lifecycle state.")
    created_at: AwareDatetime = Field(description="UTC creation time.")
    dismissed_at: AwareDatetime | None = Field(description="UTC dismissal time.")

    @model_validator(mode="after")
    def validate_conflict(self) -> Self:
        """Keep target and lifecycle fields paired and continuity scoped.

        Returns:
            Validated conflict.

        Raises:
            ValueError:
                If target, ownership, or dismissal state is contradictory.
        """

        if (self.memory_id is None) != (self.observed_revision_id is None):
            raise ValueError("Conflict target and observed revision must be paired")
        if self.evidence.scope.continuity_id != self.continuity_id:
            raise ValueError("Conflict evidence must belong to the Storyline")
        if (self.state == MemoryConflictState.DISMISSED) != (
            self.dismissed_at is not None
        ):
            raise ValueError("Dismissal time must match conflict state")
        if self.dismissed_at is not None and self.dismissed_at < self.created_at:
            raise ValueError("Conflict cannot be dismissed before creation")
        return self

    def validate_dismissal(self, command: DismissMemoryConflictCommand) -> None:
        """Validate a targeted or targetless dismissal guard.

        Args:
            command:
                Dismissal request to compare with this conflict snapshot.

        Raises:
            MemoryConflictNotFoundError:
                If the command names another conflict or Storyline.
            ExtractionEffectConflictError:
                If this conflict is already dismissed.
            StaleMemoryConflictError:
                If the command does not match the observed target revision.
        """

        if (
            command.continuity_id != self.continuity_id
            or command.conflict_id != self.id
        ):
            raise MemoryConflictNotFoundError(
                "Conflict does not match the supplied Storyline ownership"
            )
        if self.state == MemoryConflictState.DISMISSED:
            raise ExtractionEffectConflictError("Memory conflict is already dismissed")
        if command.expected_revision_id != self.observed_revision_id:
            raise StaleMemoryConflictError(
                "Dismissal does not match the conflict's observed revision"
            )


class ExtractionEffect(BaseModel):
    """Idempotent extraction effect for one source persona message.

    Attributes:
        id:
            Stable effect identifier.
        scope:
            Complete source conversation ownership.
        scene_id:
            Source scene identifier.
        source_persona_message_id:
            Unique source persona-message checkpoint.
        state:
            Reserved or terminal effect state.
        provenance:
            Configuration recorded once selection is available.
        created_at:
            UTC reservation time.
        completed_at:
            UTC terminal transition time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(description="Stable extraction-effect identifier.")
    scope: ConversationScope = Field(description="Complete source ownership.")
    scene_id: UUID = Field(description="Source scene identifier.")
    source_persona_message_id: UUID = Field(
        description="Unique source persona-message checkpoint."
    )
    state: ExtractionEffectState = Field(description="Extraction effect state.")
    provenance: ExtractionProvenance | None = Field(
        description="Terminal extraction configuration, when available."
    )
    created_at: AwareDatetime = Field(description="UTC reservation time.")
    completed_at: AwareDatetime | None = Field(description="UTC completion time.")

    @model_validator(mode="after")
    def validate_transition_snapshot(self) -> Self:
        """Require completion metadata exactly for terminal states.

        Returns:
            Validated effect snapshot.

        Raises:
            ValueError:
                If reservation and completion fields conflict.
        """

        terminal = self.state != ExtractionEffectState.RESERVED
        if terminal != (self.completed_at is not None):
            raise ValueError("Terminal extraction effects require completion time")
        if terminal != (self.provenance is not None):
            raise ValueError("Terminal extraction effects require provenance")
        if self.completed_at is not None and self.completed_at < self.created_at:
            raise ValueError("Extraction cannot complete before reservation")
        return self
