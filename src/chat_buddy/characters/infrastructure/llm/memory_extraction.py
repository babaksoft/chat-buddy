"""Provider-backed contextual Storyline memory-delta extraction."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from chat_buddy.characters.domain import (
    MAX_DELTA_COMMANDS,
    CreateMemoryCommand,
    EffectiveGeneration,
    ExtractionProvenance,
    InvalidProviderResponseError,
    MemoryDelta,
    MemoryEvidence,
    MemoryExtractionGateway,
    MemorySelectionResult,
    NoMemoryChangeCommand,
    RecordMemoryConflictCommand,
    ReinforceMemoryCommand,
    ScenePosition,
    StrategyIdentity,
    SupersedeMemoryCommand,
)
from chat_buddy.characters.prompts import (
    MEMORY_DELTA_PROMPT_SCHEMA_VERSION,
    assemble_memory_extraction_prompt,
)


class _EvidenceReference(BaseModel):
    """Provider echo of exact source evidence and occurrence.

    Attributes:
        user_message_id:
            Exact new-evidence user message.
        persona_message_id:
            Exact new-evidence persona checkpoint.
        occurrence:
            One occurrence position explicitly supplied in the prompt.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_message_id: UUID = Field(description="Source user-message identifier.")
    persona_message_id: UUID = Field(description="Source persona-message identifier.")
    occurrence: ScenePosition = Field(description="Supplied occurrence position.")


class _CreateProposal(BaseModel):
    """Strict provider syntax for a create proposal.

    Attributes:
        operation:
            Create discriminator.
        subject:
            Normalized durable subject.
        content:
            Complete supported assertion.
        evidence:
            Exact new source and supplied occurrence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    operation: Literal["create"] = Field(description="Operation discriminator.")
    subject: str = Field(min_length=1, max_length=256, description="Fact subject.")
    content: str = Field(min_length=1, max_length=4096, description="Fact content.")
    evidence: _EvidenceReference = Field(description="Exact source evidence.")


class _ReinforceProposal(BaseModel):
    """Strict provider syntax for a reinforcement proposal.

    Attributes:
        operation:
            Reinforce discriminator.
        target_memory_id:
            Opaque included memory identifier.
        expected_revision_id:
            Included current revision identifier.
        content:
            Unchanged current assertion.
        evidence:
            Exact new source and supplied occurrence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    operation: Literal["reinforce"] = Field(description="Operation discriminator.")
    target_memory_id: UUID = Field(description="Opaque target memory identifier.")
    expected_revision_id: UUID = Field(description="Observed current revision.")
    content: str = Field(min_length=1, max_length=4096, description="Current content.")
    evidence: _EvidenceReference = Field(description="Exact source evidence.")


class _SupersedeProposal(BaseModel):
    """Strict provider syntax for a supersede proposal.

    Attributes:
        operation:
            Supersede discriminator.
        target_memory_id:
            Opaque included memory identifier.
        expected_revision_id:
            Included current revision identifier.
        subject:
            Replacement normalized subject.
        content:
            Replacement assertion.
        evidence:
            Exact new source and supplied occurrence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    operation: Literal["supersede"] = Field(description="Operation discriminator.")
    target_memory_id: UUID = Field(description="Opaque target memory identifier.")
    expected_revision_id: UUID = Field(description="Observed current revision.")
    subject: str = Field(min_length=1, max_length=256, description="Fact subject.")
    content: str = Field(min_length=1, max_length=4096, description="Fact content.")
    evidence: _EvidenceReference = Field(description="Exact source evidence.")


class _ConflictProposal(BaseModel):
    """Strict provider syntax for a conflict proposal.

    Attributes:
        operation:
            Conflict discriminator.
        target_memory_id:
            Optional opaque included memory identifier.
        expected_revision_id:
            Current revision paired with a target.
        subject:
            Conflicting normalized subject.
        content:
            Conflicting assertion.
        evidence:
            Exact new source and supplied occurrence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    operation: Literal["conflict"] = Field(description="Operation discriminator.")
    target_memory_id: UUID | None = Field(description="Optional opaque target.")
    expected_revision_id: UUID | None = Field(description="Observed target revision.")
    subject: str = Field(min_length=1, max_length=256, description="Fact subject.")
    content: str = Field(min_length=1, max_length=4096, description="Fact content.")
    evidence: _EvidenceReference = Field(description="Exact source evidence.")


class _NoChangeProposal(BaseModel):
    """Strict provider syntax for an empty delta.

    Attributes:
        operation:
            No-change discriminator.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: Literal["no_change"] = Field(description="Operation discriminator.")


_ProviderCommand = Annotated[
    _CreateProposal
    | _ReinforceProposal
    | _SupersedeProposal
    | _ConflictProposal
    | _NoChangeProposal,
    Field(discriminator="operation"),
]


class _ProviderDelta(BaseModel):
    """Strict bounded provider response envelope.

    Attributes:
        commands:
            Proposed commands in provider order.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    commands: tuple[_ProviderCommand, ...] = Field(
        min_length=1,
        max_length=MAX_DELTA_COMMANDS,
        description="Bounded memory-delta commands.",
    )


class ContextualMemoryDeltaExtractor:
    """Invoke and strictly parse one configured contextual extraction model."""

    _STRATEGY_ID = StrategyIdentity(
        name="baseline.contextual_memory_delta", version="1.0.0"
    )

    def __init__(
        self,
        gateway: MemoryExtractionGateway,
        generation: EffectiveGeneration,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Bind one independently resolved provider capability.

        Args:
            gateway:
                Narrow structured-extraction provider adapter.
            generation:
                Effective memory-extraction model and configuration.
            id_factory:
                Evidence identifier factory.
            clock:
                UTC evidence timestamp source.

        Raises:
            ValueError:
                If the generation was resolved for another capability.
        """

        if generation.capability != "memory_extraction":
            raise ValueError("Extractor requires memory-extraction generation")

        self._gateway = gateway
        self._generation = generation
        self._id_factory = id_factory
        self._clock = clock

    @property
    def strategy_id(self) -> StrategyIdentity:
        """Return the extractor name and behavior version.

        Returns:
            Stable contextual extractor identity.
        """

        return self._STRATEGY_ID

    def extract(self, selection: MemorySelectionResult) -> MemoryDelta:
        """Return a detached typed proposal from one immutable snapshot.

        Args:
            selection:
                Bounded contextual snapshot and exact new source evidence.

        Returns:
            Strictly parsed delta carrying no persistence authority.

        Raises:
            InvalidProviderResponseError:
                If JSON syntax, schema, evidence, or domain shape is invalid.
        """

        schema = _ProviderDelta.model_json_schema()
        prompt = assemble_memory_extraction_prompt(selection, schema)
        response = self._gateway.extract_memory(prompt, self._generation, schema)
        try:
            proposal = _ProviderDelta.model_validate_json(response)
            delta = self._to_delta(selection, proposal)
            return delta
        except (ValidationError, ValueError) as error:
            raise InvalidProviderResponseError(
                "Memory extraction returned an invalid delta."
            ) from error

    def _to_delta(
        self, selection: MemorySelectionResult, proposal: _ProviderDelta
    ) -> MemoryDelta:
        """Attach authoritative selection and extraction provenance.

        Args:
            selection:
                Exact source snapshot.
            proposal:
                Strict provider syntax.

        Returns:
            Domain delta with normalized evidence.

        Raises:
            ValueError:
                If provider evidence was not exactly supplied by the snapshot.
        """

        created_at = self._clock()
        commands = []
        for proposal_command in proposal.commands:
            if proposal_command.operation == "no_change":
                commands.append(NoMemoryChangeCommand())
                continue

            evidence = self._evidence(selection, proposal_command.evidence, created_at)
            values = proposal_command.model_dump(exclude={"evidence"})
            if proposal_command.operation != "reinforce":
                values["occurrence"] = evidence.occurrence
            values["evidence"] = evidence
            command_types = {
                "create": CreateMemoryCommand,
                "reinforce": ReinforceMemoryCommand,
                "supersede": SupersedeMemoryCommand,
                "conflict": RecordMemoryConflictCommand,
            }
            commands.append(command_types[proposal_command.operation](**values))

        return MemoryDelta(
            selection_id=selection.id,
            scope=selection.context.scope,
            source_persona_message_id=selection.context.source_turn.persona.id,
            extractor=self.strategy_id,
            commands=tuple(commands),
        )

    def _evidence(
        self,
        selection: MemorySelectionResult,
        reference: _EvidenceReference,
        created_at: datetime,
    ) -> MemoryEvidence:
        """Validate a provider echo and construct exact trusted evidence.

        Args:
            selection:
                Exact source snapshot.
            reference:
                Provider-supplied source echo.
            created_at:
                One timestamp shared by this proposal.

        Returns:
            Complete evidence with authoritative extraction provenance.

        Raises:
            ValueError:
                If the provider invented source or temporal identifiers.
        """

        source = selection.context.source_turn
        if (
            reference.user_message_id != source.user.id
            or reference.persona_message_id != source.persona.id
        ):
            raise ValueError("Provider evidence does not match the exact source turn")

        allowed_occurrences = {selection.context.scene}
        allowed_occurrences.update(
            memory.current.source.occurrence
            for memory in selection.context.eligible_memories
            if memory.id in selection.included_memory_ids
        )
        if reference.occurrence not in allowed_occurrences:
            raise ValueError("Provider occurrence was not supplied in the snapshot")

        return MemoryEvidence(
            id=self._id_factory(),
            scope=selection.context.scope,
            scene_id=selection.context.scene.scene_id,
            user_message_id=source.user.id,
            persona_message_id=source.persona.id,
            persona_checkpoint=source.persona.sequence,
            occurrence=reference.occurrence,
            learned=selection.context.scene,
            extraction=ExtractionProvenance(
                selector=selection.selector,
                extractor=self.strategy_id,
                prompt_schema_version=MEMORY_DELTA_PROMPT_SCHEMA_VERSION,
                provider=self._generation.model.provider,
                model=self._generation.model.model,
                configuration=self._generation.configuration,
            ),
            created_at=created_at,
        )
