"""Deterministic, branch-aware evolution snapshot selection."""

from __future__ import annotations

from uuid import UUID

from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    Boundary,
    ContextCapacityError,
    ContinuityLifecycle,
    ContinuityMode,
    ContinuityRepository,
    ConversationGraphRepository,
    ConversationScope,
    EvolutionEvidence,
    EvolutionEvidenceKind,
    EvolutionEvidenceReference,
    EvolutionMemory,
    EvolutionRepository,
    EvolutionScope,
    EvolutionSnapshot,
    EvolutionSnapshotBudget,
    Identity,
    IdentityRepository,
    Persona,
    PersonaAdaptationProjection,
    PersonaRepository,
    PromptMessage,
    RelationshipIntent,
    RelationshipProjection,
    Scene,
    SceneRepository,
    StartingRelationship,
    StorylineMemory,
    StorylineMemoryRepository,
    StorylineRepository,
    StrategyIdentity,
    SummaryRepository,
    TokenCounter,
)


class BaselineEvolutionSnapshotSelector:
    """Build conservative strategy inputs from selected persisted history."""

    _SELECTOR_ID = StrategyIdentity(name="baseline.exact_evidence", version="1.0.0")

    def __init__(
        self,
        identities: IdentityRepository,
        personas: PersonaRepository,
        continuities: ContinuityRepository,
        storylines: StorylineRepository,
        scenes: SceneRepository,
        conversations: ConversationGraphRepository,
        summaries: SummaryRepository,
        memories: StorylineMemoryRepository,
        evolution: EvolutionRepository,
        counter: TokenCounter,
        budget: EvolutionSnapshotBudget,
    ) -> None:
        """Bind owned readers and deterministic token accounting.

        Args:
            identities:
                Immutable identity snapshot reader.
            personas:
                Immutable persona-core snapshot reader.
            continuities:
                Ongoing continuity ownership reader.
            storylines:
                Storyline ownership reader.
            scenes:
                Ordered Storyline scene reader.
            conversations:
                Branch-aware selected-path reader.
            summaries:
                Branch-compatible rolling-summary reader.
            memories:
                Storyline memory eligibility reader.
            evolution:
                Current relationship and adaptation projection reader.
            counter:
                Deterministic provider-specific token estimator.
            budget:
                Dedicated evolution input capacity.
        """

        self._identities = identities
        self._personas = personas
        self._continuities = continuities
        self._storylines = storylines
        self._scenes = scenes
        self._conversations = conversations
        self._summaries = summaries
        self._memories = memories
        self._evolution = evolution
        self._counter = counter
        self._budget = budget

    @property
    def selector_id(self) -> StrategyIdentity:
        """Return the stable selector identity recorded on effects.

        Returns:
            Baseline selector name and behavior version.
        """

        return self._SELECTOR_ID

    def select(
        self, scope: EvolutionScope, source: EvolutionEvidenceReference
    ) -> EvolutionSnapshot:
        """Build one bounded snapshot from a complete turn.

        Args:
            scope:
                Expected immutable continuity ownership.
            source:
                Exact newly completed selected persona checkpoint.

        Returns:
            Immutable bounded state and evidence selection.

        Raises:
            ArchivedContinuityError:
                If the owning continuity is no longer active.
            ContextCapacityError:
                If mandatory state and exact new evidence do not fit.
            ValueError:
                If ownership, mode, scene, or selected history contradicts the
                supplied source checkpoint.
        """

        if source.scope != scope:
            raise ValueError("Evolution source does not match the requested scope.")

        identity = self._identities.get(scope.identity_id)
        persona = self._personas.get(scope.persona_id)
        projections = self._evolution.get_projections(scope)
        if source.kind == EvolutionEvidenceKind.ONGOING_TURN:
            mode = ContinuityMode.ONGOING
            relationship, evidence, summary, memories = self._ongoing_inputs(
                scope, source
            )
        else:
            mode = ContinuityMode.STORYLINE
            relationship, evidence, summary, memories = self._storyline_inputs(
                scope, source
            )

        source_evidence = next(
            (item for item in evidence if item.reference == source), None
        )
        if source_evidence is None:
            raise ValueError("Evolution source is not a complete selected turn.")

        return self._budget_selection(
            scope=scope,
            mode=mode,
            identity=identity,
            persona=persona,
            relationship_intent=relationship.intent,
            boundaries=relationship.boundaries,
            relationship_projection=projections.relationship,
            adaptation_projection=projections.persona_adaptations,
            eligible_evidence=evidence,
            source=source,
            summary=summary,
            eligible_memories=memories,
        )

    def _ongoing_inputs(
        self, scope: EvolutionScope, source: EvolutionEvidenceReference
    ) -> tuple[
        StartingRelationship,
        tuple[EvolutionEvidence, ...],
        str | None,
        tuple[EvolutionMemory, ...],
    ]:
        """Load Ongoing ownership and selected evidence.

        Args:
            scope:
                Expected evolution ownership.
            source:
                Exact Ongoing source checkpoint.

        Returns:
            Starting relationship, selected evidence, summary, and no memories.
        """

        continuity = self._continuities.get(
            scope.identity_id, scope.persona_id, scope.continuity_id
        )
        if continuity.lifecycle != ContinuityLifecycle.ACTIVE:
            raise ArchivedContinuityError("Archived continuities cannot evolve.")
        if (
            continuity.mode != ContinuityMode.ONGOING
            or continuity.conversation_id != source.conversation_id
            or source.scene_id is not None
        ):
            raise ValueError("Evolution source contradicts its Ongoing continuity.")

        conversation_scope = ConversationScope(
            identity_id=scope.identity_id,
            persona_id=scope.persona_id,
            continuity_id=scope.continuity_id,
            conversation_id=source.conversation_id,
        )
        evidence = self._path_evidence(
            conversation_scope,
            EvolutionEvidenceKind.ONGOING_TURN,
            source.persona_message_id,
        )
        summary = self._compatible_summary(
            conversation_scope, source.user_message_id, source.user_sequence
        )

        return continuity.relationship, evidence, summary, ()

    def _storyline_inputs(
        self, scope: EvolutionScope, source: EvolutionEvidenceReference
    ) -> tuple[
        StartingRelationship,
        tuple[EvolutionEvidence, ...],
        str | None,
        tuple[EvolutionMemory, ...],
    ]:
        """Load Storyline-wide selected evidence and eligible memories.

        Args:
            scope:
                Expected evolution ownership.
            source:
                Exact scene checkpoint source.

        Returns:
            Starting relationship, cross-scene evidence, summary, and memories.
        """

        storyline = self._storylines.get(
            scope.identity_id, scope.persona_id, scope.continuity_id
        )
        if storyline.lifecycle != ContinuityLifecycle.ACTIVE:
            raise ArchivedContinuityError("Archived Storylines cannot evolve.")

        sequence = self._scenes.list(storyline)
        source_scene = next(
            (
                scene
                for scene in sequence.scenes
                if scene.id == source.scene_id
                and scene.position == source.scene_position
                and scene.scope.conversation_id == source.conversation_id
            ),
            None,
        )
        if source_scene is None:
            raise ValueError("Evolution source contradicts its Storyline scene.")

        evidence_parts: list[EvolutionEvidence] = []
        selected_persona_ids: set[UUID] = set()
        for scene in sequence.scenes:
            if scene.position > source_scene.position:
                break

            checkpoint = (
                source.persona_message_id if scene.id == source_scene.id else None
            )
            scene_evidence = self._path_evidence(
                scene.scope,
                EvolutionEvidenceKind.STORYLINE_CHECKPOINT,
                checkpoint,
                scene,
            )
            evidence_parts.extend(scene_evidence)
            selected_persona_ids.update(
                item.reference.persona_message_id for item in scene_evidence
            )

        evidence = tuple(evidence_parts)
        evidence_by_persona = {
            item.reference.persona_message_id: item for item in evidence
        }
        eligible_memories = self._memories.list_eligible(
            scope.continuity_id,
            source_scene.position,
            frozenset(selected_persona_ids),
        )
        memories = tuple(
            memory_context
            for memory in eligible_memories
            if (memory_context := self._memory_context(memory, evidence_by_persona))
            is not None
        )
        summary = self._compatible_summary(
            source_scene.scope, source.user_message_id, source.user_sequence
        )

        return storyline.relationship, evidence, summary, memories

    def _path_evidence(
        self,
        scope: ConversationScope,
        kind: EvolutionEvidenceKind,
        checkpoint_id: UUID | None,
        scene: Scene | None = None,
    ) -> tuple[EvolutionEvidence, ...]:
        """Convert one selected ancestry into complete exact evidence turns.

        Args:
            scope:
                Exact conversation ownership.
            kind:
                Ongoing or Storyline evidence shape.
            checkpoint_id:
                Optional final persona checkpoint for truncation.
            scene:
                Storyline scene metadata when applicable.

        Returns:
            Chronological whole selected turns through the checkpoint.

        Raises:
            ValueError:
                If the checkpoint is absent or not a complete persona turn.
        """

        path = self._conversations.selected_path(scope)
        nodes = path.messages
        if checkpoint_id is not None:
            checkpoint_index = next(
                (index for index, node in enumerate(nodes) if node.id == checkpoint_id),
                None,
            )
            if checkpoint_index is None or nodes[checkpoint_index].role != "persona":
                raise ValueError("Evolution source is not on the selected path.")

            nodes = nodes[: checkpoint_index + 1]
        elif nodes and nodes[-1].role == "user":
            nodes = nodes[:-1]

        if len(nodes) % 2:
            raise ValueError("Selected evolution ancestry is not made of whole turns.")

        result = []
        for index in range(0, len(nodes), 2):
            user = nodes[index]
            persona = nodes[index + 1]
            reference = EvolutionEvidenceReference(
                scope=EvolutionScope(
                    identity_id=scope.identity_id,
                    persona_id=scope.persona_id,
                    continuity_id=scope.continuity_id,
                ),
                kind=kind,
                conversation_id=scope.conversation_id,
                scene_id=scene.id if scene is not None else None,
                scene_position=scene.position if scene is not None else None,
                user_message_id=user.id,
                user_sequence=index + 1,
                persona_message_id=persona.id,
                persona_sequence=index + 2,
            )
            result.append(
                EvolutionEvidence(
                    reference=reference,
                    user_content=user.content,
                    persona_content=persona.content,
                )
            )

        return tuple(result)

    def _compatible_summary(
        self, scope: ConversationScope, parent_id: UUID, source_sequence: int
    ) -> str | None:
        """Read a summary compatible with ancestry before the new turn.

        Args:
            scope:
                Exact source conversation ownership.
            parent_id:
                New persona response's adjacent user parent.
            source_sequence:
                New persona position used to reject covering summaries.

        Returns:
            Compatible summary text, or None when unavailable.
        """

        summary = self._summaries.get_current(scope, path_leaf_id=parent_id)
        if summary is None or summary.checkpoint_sequence >= source_sequence:
            return None

        return summary.content

    @staticmethod
    def _memory_context(
        memory: StorylineMemory,
        evidence_by_persona: dict[UUID, EvolutionEvidence],
    ) -> EvolutionMemory | None:
        """Reduce an eligible memory to selected exact provenance.

        Args:
            memory:
                Eligible complete logical memory lineage.
            evidence_by_persona:
                Selected evidence indexed by persona checkpoint.

        Returns:
            Concise memory context, or None without selected provenance.
        """

        sources = tuple(
            evidence_by_persona[item.persona_message_id].reference
            for item in memory.evidence
            if item.persona_message_id in evidence_by_persona
        )
        if not sources:
            return None
        return EvolutionMemory(
            id=memory.id,
            subject=memory.current.subject,
            content=memory.current.content,
            sources=sources,
        )

    def _budget_selection(
        self,
        *,
        scope: EvolutionScope,
        mode: ContinuityMode,
        identity: Identity,
        persona: Persona,
        relationship_intent: RelationshipIntent,
        boundaries: tuple[Boundary, ...],
        relationship_projection: RelationshipProjection,
        adaptation_projection: PersonaAdaptationProjection,
        eligible_evidence: tuple[EvolutionEvidence, ...],
        source: EvolutionEvidenceReference,
        summary: str | None,
        eligible_memories: tuple[EvolutionMemory, ...],
    ) -> EvolutionSnapshot:
        """Admit optional whole records without displacing mandatory state.

        Args:
            scope:
                Immutable evolution ownership.
            mode:
                Ongoing or Storyline snapshot mode.
            identity:
                Immutable authored identity.
            persona:
                Immutable authored persona core.
            relationship_intent:
                User-selected relationship direction.
            boundaries:
                User-controlled restrictions.
            relationship_projection:
                Current relationship cache.
            adaptation_projection:
                Current adaptation cache.
            eligible_evidence:
                Complete selected evidence candidate set.
            source:
                Mandatory exact new turn.
            summary:
                Optional compatible interpretation context.
            eligible_memories:
                Optional continuity memories with exact provenance.

        Returns:
            Complete immutable bounded selection.

        Raises:
            ContextCapacityError:
                If mandatory authored state and source evidence do not fit.
        """

        evidence_by_reference = {item.reference: item for item in eligible_evidence}
        selected_references = {source}
        selected_memories: tuple[EvolutionMemory, ...] = ()
        selected_summary: str | None = None

        token_count = self._count(
            identity,
            persona,
            relationship_intent,
            boundaries,
            relationship_projection,
            adaptation_projection,
            selected_memories,
            selected_summary,
            self._ordered_evidence(evidence_by_reference, selected_references),
            source,
        )
        if token_count > self._budget.input_tokens:
            raise ContextCapacityError(
                "Mandatory evolution state and new evidence exceed its capacity."
            )

        for memory in eligible_memories:
            candidate_references = selected_references | set(memory.sources)
            candidate_memories = (*selected_memories, memory)
            candidate_evidence = self._ordered_evidence(
                evidence_by_reference, candidate_references
            )
            candidate_count = self._count(
                identity,
                persona,
                relationship_intent,
                boundaries,
                relationship_projection,
                adaptation_projection,
                candidate_memories,
                selected_summary,
                candidate_evidence,
                source,
            )
            if candidate_count <= self._budget.input_tokens:
                selected_references = candidate_references
                selected_memories = candidate_memories
                token_count = candidate_count

        if summary is not None:
            candidate_evidence = self._ordered_evidence(
                evidence_by_reference, selected_references
            )
            candidate_count = self._count(
                identity,
                persona,
                relationship_intent,
                boundaries,
                relationship_projection,
                adaptation_projection,
                selected_memories,
                summary,
                candidate_evidence,
                source,
            )
            if candidate_count <= self._budget.input_tokens:
                selected_summary = summary
                token_count = candidate_count

        for evidence in reversed(eligible_evidence[:-1]):
            candidate_references = selected_references | {evidence.reference}
            candidate_evidence = self._ordered_evidence(
                evidence_by_reference, candidate_references
            )
            candidate_count = self._count(
                identity,
                persona,
                relationship_intent,
                boundaries,
                relationship_projection,
                adaptation_projection,
                selected_memories,
                selected_summary,
                candidate_evidence,
                source,
            )
            if candidate_count <= self._budget.input_tokens:
                selected_references = candidate_references
                token_count = candidate_count

        selected_evidence = self._ordered_evidence(
            evidence_by_reference, selected_references
        )
        return EvolutionSnapshot(
            scope=scope,
            mode=mode,
            identity=identity,
            persona=persona,
            relationship_intent=relationship_intent,
            boundaries=boundaries,
            relationship=relationship_projection,
            persona_adaptations=adaptation_projection,
            memories=selected_memories,
            summary_context=selected_summary,
            evidence=selected_evidence,
            source=source,
            token_count=token_count,
            budget=self._budget,
        )

    @staticmethod
    def _ordered_evidence(
        evidence_by_reference: dict[EvolutionEvidenceReference, EvolutionEvidence],
        selected: set[EvolutionEvidenceReference],
    ) -> tuple[EvolutionEvidence, ...]:
        """Preserve repository chronology for an admitted reference set.

        Args:
            evidence_by_reference:
                All eligible evidence in chronological insertion order.
            selected:
                Admitted exact references.

        Returns:
            Chronological selected exact evidence.
        """

        return tuple(
            evidence
            for reference, evidence in evidence_by_reference.items()
            if reference in selected
        )

    def _count(
        self,
        identity: Identity,
        persona: Persona,
        relationship_intent: RelationshipIntent,
        boundaries: tuple[Boundary, ...],
        relationship_projection: RelationshipProjection,
        adaptation_projection: PersonaAdaptationProjection,
        memories: tuple[EvolutionMemory, ...],
        summary: str | None,
        evidence: tuple[EvolutionEvidence, ...],
        source: EvolutionEvidenceReference,
    ) -> int:
        """Count the complete stable rendering plus strategy overhead.

        Args:
            identity:
                Authored identity snapshot.
            persona:
                Authored persona-core snapshot.
            relationship_intent:
                User-selected relationship direction.
            boundaries:
                User-controlled restrictions.
            relationship_projection:
                Current relationship state.
            adaptation_projection:
                Current persona adaptations.
            memories:
                Admitted eligible memory records.
            summary:
                Admitted non-citable summary context.
            evidence:
                Admitted chronological exact turns.
            source:
                Exact new turn labeled distinctly.

        Returns:
            Conservative deterministic complete token estimate.
        """

        blocks = [
            f"[identity]\n{identity.model_dump_json()}",
            f"[persona core]\n{persona.model_dump_json()}",
            f"[relationship intent]\n{relationship_intent}",
            f"[user boundaries]\n{boundaries}",
            f"[relationship projection]\n{relationship_projection.model_dump_json()}",
            f"[persona adaptations]\n{adaptation_projection.model_dump_json()}",
        ]
        blocks.extend(
            f"[memory:{memory.id}]\nSubject: {memory.subject}\nContent: {memory.content}"
            for memory in memories
        )
        if summary is not None:
            blocks.append(f"[summary:interpretation-only]\n{summary}")
        blocks.extend(
            "\n".join(
                (
                    (
                        "[new evidence]"
                        if item.reference == source
                        else "[selected evidence]"
                    ),
                    f"Reference: {item.reference.model_dump_json()}",
                    f"User: {item.user_content}",
                    f"Persona: {item.persona_content}",
                )
            )
            for item in evidence
        )
        prompt = tuple(PromptMessage(role="system", content=block) for block in blocks)
        return self._counter.count(prompt) + self._budget.fixed_overhead_tokens
