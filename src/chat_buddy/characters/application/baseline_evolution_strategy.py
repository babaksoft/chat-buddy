"""Provider-backed conservative baseline evolution strategy."""

from __future__ import annotations

from typing import Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from chat_buddy.characters.domain import (
    MAX_COMMAND_SOURCES,
    MAX_EVOLUTION_COMMANDS,
    AdaptationFacet,
    EffectiveGeneration,
    EvolutionCommand,
    EvolutionConfiguration,
    EvolutionGateway,
    EvolutionProposal,
    EvolutionSnapshot,
    InvalidProviderResponseError,
    RelationshipMilestone,
    StrategyIdentity,
)
from chat_buddy.characters.prompts import (
    EVOLUTION_PROMPT_SCHEMA_VERSION,
    assemble_evolution_prompt,
)

BASELINE_PROVIDER_EVOLUTION_STRATEGY = StrategyIdentity(
    name="baseline.structured_evolution", version="1.0.0"
)
BASELINE_EVOLUTION_SCHEMA = StrategyIdentity(
    name="evolution.structured_prompt", version=EVOLUTION_PROMPT_SCHEMA_VERSION
)


class _ProviderCommand(BaseModel):
    """Strict bounded provider syntax translated into a domain command.

    Attributes:
        kind:
            Typed command discriminator.
        rationale:
            Concise interpretation of the cited evidence.
        evidence:
            Unique one-based snapshot evidence positions.
        expected:
            Optional observed current target value.
        value:
            Optional proposed target value.
        facet:
            Optional persona-adaptation facet.
        milestone:
            Optional explicit relationship milestone.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    kind: Literal[
        "set_social_status",
        "set_romantic_status",
        "set_dynamic",
        "set_trust",
        "set_affection",
        "record_relationship_milestone",
        "set_persona_adaptation",
        "remove_persona_adaptation",
    ] = Field(description="Typed command discriminator.")
    rationale: str = Field(
        min_length=1, max_length=1024, description="Evidence interpretation."
    )
    evidence: tuple[int, ...] = Field(
        min_length=1,
        max_length=MAX_COMMAND_SOURCES,
        description="One-based exact evidence positions.",
    )
    expected: str | None = Field(
        default=None, min_length=1, max_length=512, description="Current value."
    )
    value: str | None = Field(
        default=None, min_length=1, max_length=512, description="Proposed value."
    )
    facet: AdaptationFacet | None = Field(
        default=None, description="Persona-adaptation facet."
    )
    milestone: RelationshipMilestone | None = Field(
        default=None, description="Explicit relationship milestone."
    )

    @model_validator(mode="after")
    def validate_unique_evidence(self) -> Self:
        """Reject repeated evidence positions.

        Returns:
            Validated provider command.

        Raises:
            ValueError:
                If a position is repeated.
        """

        if len(set(self.evidence)) != len(self.evidence):
            raise ValueError("Evolution evidence positions must be unique.")

        return self


class _ProviderProposal(BaseModel):
    """Bounded provider response envelope.

    Attributes:
        commands:
            Atomic typed command syntax, empty for no change.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    commands: tuple[_ProviderCommand, ...] = Field(
        default=(),
        max_length=MAX_EVOLUTION_COMMANDS,
        description="Bounded atomic evolution commands.",
    )


class BaselineEvolutionStrategy:
    """Generate and strictly translate conservative evolution proposals."""

    def __init__(
        self,
        gateway: EvolutionGateway,
        generation: EffectiveGeneration,
        configuration: EvolutionConfiguration,
    ) -> None:
        """Bind one provider selection and its exact recorded configuration.

        Args:
            gateway:
                Narrow structured evolution provider.
            generation:
                Effective provider model and output settings.
            configuration:
                Exact selector, strategy, policy, schema, provider, and model IDs.

        Raises:
            ValueError:
                If capability or provenance does not describe this strategy.
        """

        if generation.capability != "evolution":
            raise ValueError("Baseline strategy requires evolution generation.")
        if configuration.strategy != BASELINE_PROVIDER_EVOLUTION_STRATEGY:
            raise ValueError("Evolution configuration has a different strategy.")
        if configuration.schema_identity != BASELINE_EVOLUTION_SCHEMA:
            raise ValueError("Evolution configuration has a different prompt schema.")
        if (
            configuration.provider != generation.model.provider
            or configuration.model != generation.model.model
        ):
            raise ValueError(
                "Evolution configuration has different provider provenance."
            )

        self._gateway = gateway
        self._generation = generation
        self._configuration = configuration

    @property
    def strategy_id(self) -> StrategyIdentity:
        """Return the stable baseline strategy identity.

        Returns:
            Versioned provider-backed baseline identity.
        """

        return BASELINE_PROVIDER_EVOLUTION_STRATEGY

    def propose(self, snapshot: EvolutionSnapshot) -> EvolutionProposal:
        """Generate a detached typed proposal from one immutable snapshot.

        Args:
            snapshot:
                Bounded state and exact eligible evidence.

        Returns:
            Typed atomic proposal with authoritative scope and provenance.

        Raises:
            InvalidProviderResponseError:
                If provider JSON, evidence, or command shape is invalid.
        """

        schema = _ProviderProposal.model_json_schema()
        prompt = assemble_evolution_prompt(snapshot, schema)
        response = self._gateway.propose_evolution(prompt, self._generation, schema)
        try:
            provider_proposal = _ProviderProposal.model_validate_json(response)
            commands = tuple(
                self._to_command(command, snapshot)
                for command in provider_proposal.commands
            )

            return EvolutionProposal(
                id=self._proposal_id(snapshot),
                scope=snapshot.scope,
                expected_relationship_revision=snapshot.relationship.revision,
                expected_adaptation_revision=snapshot.persona_adaptations.revision,
                source=snapshot.source,
                provenance=self._configuration.provenance(),
                commands=commands,
            )
        except (ValidationError, ValueError) as error:
            raise InvalidProviderResponseError(
                "Evolution provider returned an invalid proposal."
            ) from error

    @staticmethod
    def _to_command(
        command: _ProviderCommand, snapshot: EvolutionSnapshot
    ) -> EvolutionCommand:
        """Attach exact snapshot references and validate the domain command.

        Args:
            command:
                Strict provider wire command.
            snapshot:
                Authoritative evidence selection.

        Returns:
            Fully typed domain command.

        Raises:
            ValueError:
                If evidence is out of range, omits the source, or shape is invalid.
        """

        source_position = len(snapshot.evidence)
        if source_position not in command.evidence:
            raise ValueError("Every evolution command must cite the new source.")

        try:
            sources = tuple(
                snapshot.evidence[position - 1].reference
                for position in command.evidence
                if position > 0
            )
        except IndexError:
            raise ValueError("Evolution evidence position is out of range.") from None
        if len(sources) != len(command.evidence):
            raise ValueError("Evolution evidence positions must be positive.")

        values = command.model_dump(exclude={"evidence"}, exclude_none=True)
        values["sources"] = sources

        return TypeAdapter(EvolutionCommand).validate_python(values)

    def _proposal_id(self, snapshot: EvolutionSnapshot) -> UUID:
        """Derive a stable proposal ID for one source and strategy version.

        Args:
            snapshot:
                Snapshot supplying the exact source identifier.

        Returns:
            Deterministic proposal identifier.
        """

        return uuid5(
            NAMESPACE_URL,
            ":".join(
                (
                    str(snapshot.scope.continuity_id),
                    str(snapshot.source.persona_message_id),
                    self.strategy_id.name,
                    self.strategy_id.version,
                )
            ),
        )
