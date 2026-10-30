"""Idempotent post-response relationship and persona evolution orchestration."""

from __future__ import annotations

from uuid import UUID

from chat_buddy.characters.application.evolution import (
    EvolutionEvaluator,
    EvolutionProposalValidator,
)
from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    ContinuityLifecycle,
    ContinuityMode,
    ContinuityRepository,
    ConversationGraphRepository,
    ConversationTarget,
    EvolutionConfiguration,
    EvolutionConfigurationResolver,
    EvolutionDecisionOutcome,
    EvolutionEffect,
    EvolutionEffectConflictError,
    EvolutionEffectState,
    EvolutionEvidenceKind,
    EvolutionEvidenceReference,
    EvolutionProjectionConflictError,
    EvolutionRepository,
    EvolutionScope,
    EvolutionSnapshotSelector,
    EvolutionStrategy,
    EvolutionThresholdPolicy,
    PersonaAdaptationProjection,
    RelationshipAffection,
    RelationshipDynamic,
    RelationshipProjection,
    RelationshipRomanticStatus,
    RelationshipSocialStatus,
    RelationshipTrust,
    SceneRepository,
    StartingRelationship,
    StorylineRepository,
)


class EvolutionEffectService:
    """Process one selected completed turn through a durable evolution effect."""

    def __init__(
        self,
        conversations: ConversationGraphRepository,
        continuities: ContinuityRepository,
        storylines: StorylineRepository,
        scenes: SceneRepository,
        repository: EvolutionRepository,
        selector: EvolutionSnapshotSelector,
        configuration_resolver: EvolutionConfigurationResolver,
        strategy: EvolutionStrategy,
        threshold_policy: EvolutionThresholdPolicy,
    ) -> None:
        """Bind exact-history readers and replaceable evolution components.

        Args:
            conversations:
                Selected conversation ancestry reader.
            continuities:
                Ongoing lifecycle and starting-state reader.
            storylines:
                Storyline lifecycle and starting-state reader.
            scenes:
                Storyline scene position reader.
            repository:
                Durable effect, event, and projection persistence.
            selector:
                Immutable bounded snapshot builder.
            configuration_resolver:
                Continuity-stable experimental assignment resolver.
            strategy:
                Typed proposal implementation.
            threshold_policy:
                Versioned gradual-change calibration policy.
        """

        self._conversations = conversations
        self._continuities = continuities
        self._storylines = storylines
        self._scenes = scenes
        self._repository = repository
        self._selector = selector
        self._configuration_resolver = configuration_resolver
        self._strategy = strategy
        self._threshold_policy = threshold_policy

    def process(
        self, target: ConversationTarget, source_persona_message_id: UUID
    ) -> EvolutionEffect:
        """Reserve, evaluate, and atomically complete one selected checkpoint.

        A failure after reservation is deliberately allowed to propagate. The
        visible response is already committed by the caller, while the reserved
        effect remains resumable by a later call.

        Args:
            target:
                Exact Ongoing conversation or Storyline scene target.
            source_persona_message_id:
                Newly committed or retryable selected persona checkpoint.

        Returns:
            Existing or newly completed durable evolution effect.

        Raises:
            ArchivedContinuityError:
                If the owning continuity is archived.
            ValueError:
                If the source is incomplete, unselected, foreign, or component
                identities contradict the resolved configuration.
        """

        scope = EvolutionScope(
            identity_id=target.scope.identity_id,
            persona_id=target.scope.persona_id,
            continuity_id=target.scope.continuity_id,
        )
        source, starting_relationship = self._source(
            target, scope, source_persona_message_id
        )
        configuration = self._configuration_resolver.resolve(scope.continuity_id)
        self._validate_configuration(configuration)
        effect = self._repository.reserve(source, configuration.provenance())
        if effect.state != EvolutionEffectState.RESERVED:
            return effect

        try:
            self._repository.get_projections(scope)
        except EvolutionProjectionConflictError:
            self._repository.initialize(
                _relationship_projection(scope, starting_relationship),
                PersonaAdaptationProjection(scope=scope, revision=0),
            )

        snapshot = self._selector.select(scope, source)
        proposal = EvolutionEvaluator(self._strategy, configuration).evaluate(snapshot)
        result = EvolutionProposalValidator(self._threshold_policy).evaluate(
            snapshot, proposal
        )

        try:
            if result.decision.outcome == EvolutionDecisionOutcome.APPLIED:
                return self._repository.complete(
                    effect.id,
                    proposal,
                    result.decision,
                    result.relationship,
                    result.persona_adaptations,
                )

            return self._repository.complete(effect.id, proposal, result.decision)
        except EvolutionEffectConflictError:
            terminal = self._repository.get_effect(scope, source.persona_message_id)
            if terminal.state != EvolutionEffectState.RESERVED:
                return terminal

            raise

    def _source(
        self,
        target: ConversationTarget,
        scope: EvolutionScope,
        source_persona_message_id: UUID,
    ) -> tuple[EvolutionEvidenceReference, StartingRelationship]:
        """Resolve one selected whole turn and its active starting state.

        Args:
            target:
                Exact mode-owned conversation target.
            scope:
                Evolution ownership derived from the target.
            source_persona_message_id:
                Persona checkpoint that must occur on selected ancestry.

        Returns:
            Exact evidence reference and immutable starting relationship.

        Raises:
            ArchivedContinuityError:
                If the owning continuity is archived.
            ValueError:
                If the source is not a complete selected persona turn.
        """

        path = self._conversations.selected_path(target.scope)
        index = next(
            (
                position
                for position, message in enumerate(path.messages)
                if message.id == source_persona_message_id
            ),
            None,
        )
        if (
            index is None
            or index == 0
            or path.messages[index].role != "persona"
            or path.messages[index - 1].role != "user"
            or path.messages[index].parent_id != path.messages[index - 1].id
        ):
            raise ValueError("Evolution requires a complete selected persona turn.")

        user = path.messages[index - 1]
        persona = path.messages[index]
        scene_id = None
        scene_position = None
        if target.mode == ContinuityMode.ONGOING:
            continuity = self._continuities.get(
                scope.identity_id, scope.persona_id, scope.continuity_id
            )
            if continuity.lifecycle != ContinuityLifecycle.ACTIVE:
                raise ArchivedContinuityError("Archived continuities cannot evolve.")
            if continuity.conversation_id != target.scope.conversation_id:
                raise ValueError("Evolution target contradicts its Ongoing owner.")

            kind = EvolutionEvidenceKind.ONGOING_TURN
            starting_relationship = continuity.relationship
        elif target.mode == ContinuityMode.STORYLINE:
            storyline = self._storylines.get(
                scope.identity_id, scope.persona_id, scope.continuity_id
            )
            if storyline.lifecycle != ContinuityLifecycle.ACTIVE:
                raise ArchivedContinuityError("Archived Storylines cannot evolve.")
            if target.scene_id is None:
                raise ValueError("Storyline evolution requires a scene owner.")

            scene = self._scenes.get(target.scope, target.scene_id)
            kind = EvolutionEvidenceKind.STORYLINE_CHECKPOINT
            scene_id = scene.id
            scene_position = scene.position
            starting_relationship = storyline.relationship
        else:
            raise ValueError("Timeline evolution is not available.")

        return (
            EvolutionEvidenceReference(
                scope=scope,
                kind=kind,
                conversation_id=target.scope.conversation_id,
                scene_id=scene_id,
                scene_position=scene_position,
                user_message_id=user.id,
                user_sequence=index,
                persona_message_id=persona.id,
                persona_sequence=index + 1,
            ),
            starting_relationship,
        )

    def _validate_configuration(self, configuration: EvolutionConfiguration) -> None:
        """Require resolved identities to match all bound implementations.

        Args:
            configuration:
                Candidate resolved configuration.

        Raises:
            ValueError:
                If the value or any component identity is contradictory.
        """

        if configuration.selector != self._selector.selector_id:
            raise ValueError("Evolution configuration selector does not match.")
        if configuration.strategy != self._strategy.strategy_id:
            raise ValueError("Evolution configuration strategy does not match.")
        if configuration.threshold_policy != self._threshold_policy.policy_id:
            raise ValueError("Evolution configuration policy does not match.")


def _relationship_projection(
    scope: EvolutionScope, relationship: StartingRelationship
) -> RelationshipProjection:
    """Convert immutable starting state to the revision-zero cache.

    Args:
        scope:
            Evolution projection ownership.
        relationship:
            Reviewed starting relationship.

    Returns:
        Revision-zero qualitative relationship projection.
    """

    return RelationshipProjection(
        scope=scope,
        revision=0,
        social=RelationshipSocialStatus(relationship.social),
        romantic=RelationshipRomanticStatus(relationship.romantic),
        dynamic=RelationshipDynamic(relationship.dynamic),
        trust=RelationshipTrust(relationship.trust),
        affection=RelationshipAffection(relationship.affection),
    )
