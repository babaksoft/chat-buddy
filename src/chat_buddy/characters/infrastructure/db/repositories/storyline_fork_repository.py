"""Atomic structural copying for reviewed Storyline forks."""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    ConfirmationConflictError,
    EvolutionCommand,
    EvolutionCorrectionAction,
    EvolutionCorrectionEvent,
    EvolutionDecision,
    EvolutionDecisionOutcome,
    EvolutionEvent,
    EvolutionEvidenceReference,
    EvolutionProposal,
    EvolutionScope,
    Identity,
    Persona,
    PersonaAdaptationProjection,
    RelationshipAffection,
    RelationshipDynamic,
    RelationshipProjection,
    RelationshipRomanticStatus,
    RelationshipSocialStatus,
    RelationshipTrust,
    ResponseProvenance,
    StartingRelationship,
    StorylineForkConflictError,
    StorylineForkMapping,
    StorylineForkPreview,
    StorylineForkResult,
    apply_evolution_command,
    is_adaptation_command,
)
from chat_buddy.characters.infrastructure.db.models import (
    ContinuityModel,
    ConversationModel,
    EvolutionCorrectionEventModel,
    EvolutionEffectModel,
    EvolutionEventModel,
    GenerationAttemptModel,
    IdentityModel,
    MemoryEvidenceModel,
    MemoryRevisionModel,
    MessageModel,
    PersonaAdaptationProjectionModel,
    PersonaModel,
    RelationshipProjectionModel,
    SceneModel,
    StartingRelationshipModel,
    StorylineMemoryModel,
    StorylineModel,
    SummaryRevisionModel,
)

_EVOLUTION_COMMAND_ADAPTER: TypeAdapter[EvolutionCommand] = TypeAdapter(
    EvolutionCommand
)


@dataclass
class _EvolutionCopyState:
    """Accumulate remapped evolution history during one atomic fork.

    Attributes:
        mappings:
            Evolution-specific source-to-target identifier mappings.
        events:
            Eligible inferred events copied in replay order.
        corrections:
            Eligible user corrections copied in replay order.
        event_ids:
            Source inferred-event IDs mapped to target IDs.
        events_by_id:
            Target inferred events indexed for correction remapping.
        relationship_revision:
            Normalized target relationship revision.
        adaptation_revision:
            Normalized target persona-adaptation revision.
    """

    mappings: list[StorylineForkMapping] = field(default_factory=list)
    events: list[EvolutionEvent] = field(default_factory=list)
    corrections: list[EvolutionCorrectionEvent] = field(default_factory=list)
    event_ids: dict[UUID, UUID] = field(default_factory=dict)
    events_by_id: dict[UUID, EvolutionEvent] = field(default_factory=dict)
    relationship_revision: int = 0
    adaptation_revision: int = 0

    def advance(self, command: EvolutionCommand) -> tuple[int, int]:
        """Advance the normalized revision targeted by one command.

        Args:
            command:
                Copied inferred or corrected command.

        Returns:
            Relationship and adaptation revisions after the command.
        """

        if is_adaptation_command(command):
            self.adaptation_revision += 1
        else:
            self.relationship_revision += 1
        return self.relationship_revision, self.adaptation_revision


from chat_buddy.characters.infrastructure.db.repositories.identity_repository import (
    DbIdentityRepository,
)
from chat_buddy.characters.infrastructure.db.repositories.persona_repository import (
    DbPersonaRepository,
)
from chat_buddy.characters.infrastructure.db.repositories.storyline_repository import (
    DbStorylineRepository,
)


class DbStorylineForkRepository:
    """Copy selected Storyline structure under one serializable ownership lock."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Initialize the fork repository.

        Args:
            session_factory:
                Factory used for short database transactions.
        """

        self._factory = session_factory

    def find_confirmation(
        self, preview: StorylineForkPreview
    ) -> StorylineForkResult | None:
        """Read an identical prior fork confirmation.

        Args:
            preview:
                Complete reviewed fork input.

        Returns:
            Original fork result, or None.
        """

        with self._factory() as session:
            continuity = self._confirmation(session, preview)
            return None if continuity is None else self._result(session, continuity)

    def fork(self, preview: StorylineForkPreview) -> StorylineForkResult:
        """Atomically copy selected paths and remap every owned identifier.

        Args:
            preview:
                Reviewed source, branch point, name, and target profiles.

        Returns:
            New or idempotently existing structural fork.

        Raises:
            StorylineForkConflictError:
                If any reviewed source or target guard changed.
        """

        try:
            with self._factory() as session, session.begin():
                existing = self._confirmation(session, preview)
                if existing is not None:
                    return self._result(session, existing)

                result = self._copy(session, preview)
                session.flush()
                return result
        except IntegrityError as error:
            with self._factory() as session:
                existing = self._confirmation(session, preview)
                if existing is not None:
                    return self._result(session, existing)

            raise StorylineForkConflictError(
                "Source state or target ownership changed during the fork"
            ) from error

    def _copy(
        self, session: Session, preview: StorylineForkPreview
    ) -> StorylineForkResult:
        """Validate locked state and construct the independent graph copy.

        Args:
            session:
                Current transaction.
            preview:
                Reviewed fork input.

        Returns:
            Detached fork result before commit.
        """

        source = session.scalar(
            select(StorylineModel)
            .where(
                StorylineModel.continuity_id == preview.source.scope.continuity_id,
                StorylineModel.identity_id == preview.source.scope.identity_id,
                StorylineModel.persona_id == preview.source.scope.persona_id,
                StorylineModel.mode == "storyline",
            )
            .with_for_update()
        )
        if source is None:
            raise StorylineForkConflictError("Source Storyline ownership changed")

        existing = self._confirmation(session, preview)
        if existing is not None:
            return self._result(session, existing)

        source_continuity = DbStorylineRepository._continuity(
            session, source, lock=True
        )
        if (
            source_continuity.lifecycle != "active"
            or source.revision != preview.source.expected_storyline_revision
        ):
            raise StorylineForkConflictError("Source Storyline changed after review")

        source_identity = self._identity(session, preview.source_identity.id, lock=True)
        source_persona = self._persona(session, preview.source_persona.id, lock=True)
        target_identity = self._identity(session, preview.target_identity.id, lock=True)
        target_persona = self._persona(session, preview.target_persona.id, lock=True)
        self._require_identity_snapshot(source_identity, preview.source_identity)
        self._require_persona_snapshot(source_persona, preview.source_persona)
        self._require_identity_snapshot(target_identity, preview.target_identity)
        self._require_persona_snapshot(target_persona, preview.target_persona)

        occupied = session.scalar(
            select(StorylineModel.continuity_id)
            .where(
                StorylineModel.identity_id == target_identity.id,
                StorylineModel.persona_id == target_persona.id,
            )
            .limit(1)
        )
        if occupied is not None:
            raise StorylineForkConflictError(
                "The reviewed target pair already owns a Storyline"
            )

        source_scenes = tuple(
            session.scalars(
                select(SceneModel)
                .where(SceneModel.continuity_id == source.continuity_id)
                .order_by(SceneModel.position)
                .with_for_update()
            )
        )
        if (
            not source_scenes
            or source_scenes[-1].position <= preview.source.scene_position
        ):
            raise StorylineForkConflictError(
                "The reviewed source no longer has a dependent later scene"
            )

        copied_sources = source_scenes[: preview.source.scene_position]
        final_scene = copied_sources[-1]
        if (
            final_scene.id != preview.source.scene_id
            or final_scene.conversation_id != preview.source.scope.conversation_id
            or final_scene.position != preview.source.scene_position
        ):
            raise StorylineForkConflictError("Source scene ownership changed")

        final_conversation = self._conversation(session, final_scene)
        if (
            final_conversation.selected_leaf_id
            != preview.source.expected_selected_leaf_id
        ):
            raise StorylineForkConflictError("Source selection changed after review")

        target_identity.is_frozen = True
        target_persona.is_frozen = True
        target_continuity = ContinuityModel(
            identity_id=target_identity.id,
            persona_id=target_persona.id,
            mode="storyline",
            lifecycle="active",
            request_id=preview.request_id,
            confirmed_request=preview.model_dump(mode="json"),
        )
        session.add(target_continuity)
        session.flush()

        target_storyline = StorylineModel(
            continuity_id=target_continuity.id,
            identity_id=target_identity.id,
            persona_id=target_persona.id,
            mode="storyline",
            name=preview.name,
            revision=1,
        )
        relationship = session.scalars(
            select(StartingRelationshipModel).where(
                StartingRelationshipModel.continuity_id == source.continuity_id
            )
        ).one()
        session.add_all(
            [
                target_storyline,
                StartingRelationshipModel(
                    continuity_id=target_continuity.id,
                    identity_id=target_identity.id,
                    persona_id=target_persona.id,
                    snapshot=deepcopy(relationship.snapshot),
                ),
            ]
        )

        mappings = [
            StorylineForkMapping(
                kind="identity",
                source_id=source_identity.id,
                target_id=target_identity.id,
            ),
            StorylineForkMapping(
                kind="persona",
                source_id=source_persona.id,
                target_id=target_persona.id,
            ),
            StorylineForkMapping(
                kind="continuity",
                source_id=source.continuity_id,
                target_id=target_continuity.id,
            ),
        ]
        target_scenes: list[SceneModel] = []
        for source_scene in copied_sources:
            target_scene, scene_mappings = self._copy_scene(
                session,
                preview,
                source_scene,
                target_continuity,
                source_scene.id == preview.source.scene_id,
            )
            target_scenes.append(target_scene)
            mappings.extend(scene_mappings)

        mappings.extend(
            self._copy_memories(
                session,
                source.continuity_id,
                target_continuity,
                mappings,
            )
        )
        mappings.extend(
            self._copy_evolution(
                session,
                source.continuity_id,
                target_continuity,
                relationship,
                mappings,
            )
        )

        target_storyline.fork_provenance = {
            "branch_point_message_id": str(preview.source.branch_point_message_id),
            "mappings": [mapping.model_dump(mode="json") for mapping in mappings],
        }
        session.flush()

        return StorylineForkResult(
            storyline=DbStorylineRepository._snapshot(session, target_storyline),
            scenes=tuple(
                DbStorylineRepository._scene_snapshot(scene) for scene in target_scenes
            ),
            mappings=tuple(mappings),
        )

    def _copy_scene(
        self,
        session: Session,
        preview: StorylineForkPreview,
        source_scene: SceneModel,
        target_continuity: ContinuityModel,
        is_branch_scene: bool,
    ) -> tuple[SceneModel, list[StorylineForkMapping]]:
        """Copy one selected ancestry, its attempts, and compatible summaries.

        Args:
            session:
                Current transaction.
            preview:
                Reviewed fork input.
            source_scene:
                Source scene copied at the same ordinal.
            target_continuity:
                New independent continuity owner.
            is_branch_scene:
                Whether the path ends at the chosen branch point.

        Returns:
            Target scene row and complete mappings created for it.
        """

        source_conversation = self._conversation(session, source_scene)
        leaf_id = (
            preview.source.branch_point_message_id
            if is_branch_scene
            else source_conversation.selected_leaf_id
        )
        if leaf_id is None:
            raise StorylineForkConflictError("A copied source scene is incomplete")

        path = self._path(session, source_conversation, leaf_id)
        if not path or path[-1].role != "persona":
            raise StorylineForkConflictError("A copied source scene is incomplete")

        open_attempt = session.scalar(
            select(GenerationAttemptModel.id)
            .where(
                GenerationAttemptModel.conversation_id == source_conversation.id,
                GenerationAttemptModel.continuity_id
                == source_conversation.continuity_id,
                GenerationAttemptModel.status.in_(["pending", "streaming"]),
            )
            .limit(1)
        )
        if open_attempt is not None:
            raise StorylineForkConflictError(
                "An open attempt prevents a complete source snapshot"
            )

        target_conversation = ConversationModel(
            continuity_id=target_continuity.id,
            identity_id=target_continuity.identity_id,
            persona_id=target_continuity.persona_id,
            mode="storyline",
            generation_settings=deepcopy(source_conversation.generation_settings),
        )
        session.add(target_conversation)
        session.flush()

        target_scene = SceneModel(
            continuity_id=target_continuity.id,
            identity_id=target_continuity.identity_id,
            persona_id=target_continuity.persona_id,
            conversation_id=target_conversation.id,
            mode="storyline",
            position=source_scene.position,
            title=source_scene.title,
            setup=source_scene.setup,
            response_style=deepcopy(source_scene.response_style),
            setup_locked=True,
        )
        session.add(target_scene)
        session.flush()

        mappings = [
            StorylineForkMapping(
                kind="scene", source_id=source_scene.id, target_id=target_scene.id
            ),
            StorylineForkMapping(
                kind="conversation",
                source_id=source_conversation.id,
                target_id=target_conversation.id,
            ),
        ]

        message_ids = {source_message.id: uuid4() for source_message in path}
        source_attempts: dict[UUID, GenerationAttemptModel] = {}
        attempt_ids: dict[UUID, UUID] = {}
        for source_message in path:
            provenance = None
            if source_message.role == "persona":
                source_attempt = session.scalar(
                    select(GenerationAttemptModel).where(
                        GenerationAttemptModel.persona_message_id == source_message.id,
                        GenerationAttemptModel.conversation_id
                        == source_conversation.id,
                        GenerationAttemptModel.continuity_id
                        == source_conversation.continuity_id,
                        GenerationAttemptModel.status == "completed",
                    )
                )
                if source_attempt is None:
                    raise StorylineForkConflictError(
                        "Persona provenance has no completed source attempt"
                    )

                source_attempts[source_message.id] = source_attempt
                attempt_ids[source_attempt.id] = uuid4()
                provenance_value = ResponseProvenance.model_validate(
                    source_message.response_provenance
                ).model_copy(update={"attempt_id": attempt_ids[source_attempt.id]})
                provenance = provenance_value.model_dump(mode="json")

            target_message = MessageModel(
                id=message_ids[source_message.id],
                conversation_id=target_conversation.id,
                continuity_id=target_continuity.id,
                role=source_message.role,
                content=source_message.content,
                parent_id=(
                    None
                    if source_message.parent_id is None
                    else message_ids[source_message.parent_id]
                ),
                created_at=source_message.created_at,
            )
            if provenance is not None:
                target_message.response_provenance = provenance

            session.add(target_message)
            mappings.append(
                StorylineForkMapping(
                    kind="message",
                    source_id=source_message.id,
                    target_id=message_ids[source_message.id],
                )
            )

        session.flush()

        for source_message_id, source_attempt in source_attempts.items():
            mapped_user_id = message_ids.get(source_attempt.user_message_id)
            if mapped_user_id is None:
                raise StorylineForkConflictError(
                    "Completed attempt user is outside the copied ancestry"
                )

            target_attempt_id = attempt_ids[source_attempt.id]
            session.add(
                GenerationAttemptModel(
                    id=target_attempt_id,
                    conversation_id=target_conversation.id,
                    continuity_id=target_continuity.id,
                    user_message_id=mapped_user_id,
                    selection_guard_id=mapped_user_id,
                    persona_message_id=message_ids[source_message_id],
                    submitted_input=source_attempt.submitted_input,
                    generation=deepcopy(source_attempt.generation),
                    status="completed",
                    incomplete_output=source_attempt.incomplete_output,
                    created_at=source_attempt.created_at,
                    updated_at=source_attempt.updated_at,
                    finished_at=source_attempt.finished_at,
                )
            )
            mappings.append(
                StorylineForkMapping(
                    kind="attempt",
                    source_id=source_attempt.id,
                    target_id=target_attempt_id,
                )
            )
        session.flush()

        target_conversation.selected_leaf_id = message_ids[path[-1].id]
        session.flush()

        mappings.extend(
            self._copy_summaries(
                session,
                source_conversation,
                target_conversation,
                message_ids,
            )
        )

        return target_scene, mappings

    @staticmethod
    def _copy_memories(
        session: Session,
        source_continuity_id: UUID,
        target_continuity: ContinuityModel,
        mappings: list[StorylineForkMapping],
    ) -> list[StorylineForkMapping]:
        """Copy active lineages supported entirely by copied source histories.

        Args:
            session:
                Current atomic fork transaction.
            source_continuity_id:
                Source Storyline memory owner.
            target_continuity:
                Independent fork owner.
            mappings:
                Structural mappings created before memory is considered.

        Returns:
            Memory, revision, and supporting-evidence identifier mappings.
        """

        mapped = {
            kind: {
                mapping.source_id: mapping.target_id
                for mapping in mappings
                if mapping.kind == kind
            }
            for kind in ("scene", "conversation", "message")
        }
        source_memories = tuple(
            session.scalars(
                select(StorylineMemoryModel)
                .where(StorylineMemoryModel.continuity_id == source_continuity_id)
                .order_by(StorylineMemoryModel.id)
                .with_for_update()
            )
        )

        copied_mappings: list[StorylineForkMapping] = []
        for source_memory in source_memories:
            revisions = tuple(
                session.scalars(
                    select(MemoryRevisionModel)
                    .where(
                        MemoryRevisionModel.memory_id == source_memory.id,
                        MemoryRevisionModel.continuity_id == source_continuity_id,
                    )
                    .order_by(MemoryRevisionModel.revision)
                    .with_for_update()
                )
            )
            current = next(
                (
                    revision
                    for revision in revisions
                    if revision.id == source_memory.current_revision_id
                ),
                None,
            )
            if current is None or current.state != "active":
                continue

            evidence = tuple(
                session.scalars(
                    select(MemoryEvidenceModel)
                    .where(
                        MemoryEvidenceModel.memory_id == source_memory.id,
                        MemoryEvidenceModel.continuity_id == source_continuity_id,
                        MemoryEvidenceModel.purpose == "support",
                    )
                    .order_by(MemoryEvidenceModel.created_at, MemoryEvidenceModel.id)
                    .with_for_update()
                )
            )
            copyable_evidence = tuple(
                item
                for item in evidence
                if item.scene_id in mapped["scene"]
                and item.occurrence_scene_id in mapped["scene"]
                and item.learned_scene_id in mapped["scene"]
                and item.conversation_id in mapped["conversation"]
                and item.user_message_id in mapped["message"]
                and item.source_persona_message_id in mapped["message"]
            )
            copyable_evidence_ids = {item.id for item in copyable_evidence}
            required_evidence_ids = {
                revision.source_evidence_id for revision in revisions
            }
            if (
                current.source_evidence_id not in copyable_evidence_ids
                or not required_evidence_ids <= copyable_evidence_ids
            ):
                continue

            target_memory_id = uuid4()
            target_memory = StorylineMemoryModel(
                id=target_memory_id,
                continuity_id=target_continuity.id,
                identity_id=target_continuity.identity_id,
                persona_id=target_continuity.persona_id,
                current_revision_id=None,
                subject_key=source_memory.subject_key,
            )
            session.add(target_memory)
            session.flush()
            copied_mappings.append(
                StorylineForkMapping(
                    kind="memory",
                    source_id=source_memory.id,
                    target_id=target_memory_id,
                )
            )

            evidence_ids: dict[UUID, UUID] = {}
            for source_evidence in copyable_evidence:
                target_evidence_id = uuid4()
                evidence_ids[source_evidence.id] = target_evidence_id
                session.add(
                    MemoryEvidenceModel(
                        id=target_evidence_id,
                        memory_id=target_memory_id,
                        continuity_id=target_continuity.id,
                        identity_id=target_continuity.identity_id,
                        persona_id=target_continuity.persona_id,
                        conversation_id=mapped["conversation"][
                            source_evidence.conversation_id
                        ],
                        mode="storyline",
                        purpose="support",
                        scene_id=mapped["scene"][source_evidence.scene_id],
                        user_message_id=mapped["message"][
                            source_evidence.user_message_id
                        ],
                        source_persona_message_id=mapped["message"][
                            source_evidence.source_persona_message_id
                        ],
                        persona_checkpoint=source_evidence.persona_checkpoint,
                        occurrence_scene_id=mapped["scene"][
                            source_evidence.occurrence_scene_id
                        ],
                        occurrence_position=source_evidence.occurrence_position,
                        learned_scene_id=mapped["scene"][
                            source_evidence.learned_scene_id
                        ],
                        learned_position=source_evidence.learned_position,
                        extraction=deepcopy(source_evidence.extraction),
                        created_at=source_evidence.created_at,
                    )
                )
                copied_mappings.append(
                    StorylineForkMapping(
                        kind="memory_evidence",
                        source_id=source_evidence.id,
                        target_id=target_evidence_id,
                    )
                )
            session.flush()

            revision_ids: dict[UUID, UUID] = {}
            for source_revision in revisions:
                target_revision_id = uuid4()
                revision_ids[source_revision.id] = target_revision_id
                session.add(
                    MemoryRevisionModel(
                        id=target_revision_id,
                        memory_id=target_memory_id,
                        continuity_id=target_continuity.id,
                        revision=source_revision.revision,
                        predecessor_id=(
                            None
                            if source_revision.predecessor_id is None
                            else revision_ids[source_revision.predecessor_id]
                        ),
                        subject=source_revision.subject,
                        content=source_revision.content,
                        state=source_revision.state,
                        authorship=source_revision.authorship,
                        kind=source_revision.kind,
                        source_evidence_id=evidence_ids[
                            source_revision.source_evidence_id
                        ],
                        created_at=source_revision.created_at,
                    )
                )
                copied_mappings.append(
                    StorylineForkMapping(
                        kind="memory_revision",
                        source_id=source_revision.id,
                        target_id=target_revision_id,
                    )
                )
            session.flush()

            target_memory.current_revision_id = revision_ids[current.id]
            session.flush()

        return copied_mappings

    @staticmethod
    def _copy_evolution(
        session: Session,
        source_continuity_id: UUID,
        target_continuity: ContinuityModel,
        starting_relationship: StartingRelationshipModel,
        mappings: list[StorylineForkMapping],
    ) -> list[StorylineForkMapping]:
        """Copy eligible evolution audit history and rebuild independent caches.

        Args:
            session:
                Current atomic fork transaction.
            source_continuity_id:
                Source Storyline evolution owner.
            target_continuity:
                Independent fork owner.
            starting_relationship:
                Copied user-authored starting relationship.
            mappings:
                Structural identifiers available for evidence remapping.

        Returns:
            Effect, proposal, event, correction, and projection mappings.
        """

        mapped = DbStorylineForkRepository._evolution_structural_mappings(mappings)
        target_scope = EvolutionScope(
            identity_id=target_continuity.identity_id,
            persona_id=target_continuity.persona_id,
            continuity_id=target_continuity.id,
        )
        state = _EvolutionCopyState()

        DbStorylineForkRepository._copy_evolution_effects(
            session, source_continuity_id, target_scope, mapped, state
        )
        DbStorylineForkRepository._copy_evolution_corrections(
            session, source_continuity_id, target_scope, mapped, state
        )
        DbStorylineForkRepository._persist_evolution_projections(
            session,
            source_continuity_id,
            target_scope,
            StartingRelationship.model_validate(starting_relationship.snapshot),
            state,
        )
        session.flush()

        return state.mappings

    @staticmethod
    def _evolution_structural_mappings(
        mappings: list[StorylineForkMapping],
    ) -> dict[str, dict[UUID, UUID]]:
        """Index copied structural identifiers used by evolution evidence.

        Args:
            mappings:
                All structural mappings created before evolution is considered.

        Returns:
            Scene, conversation, and message mappings indexed by source ID.
        """

        return {
            kind: {
                mapping.source_id: mapping.target_id
                for mapping in mappings
                if mapping.kind == kind
            }
            for kind in ("scene", "conversation", "message")
        }

    @staticmethod
    def _copy_evolution_effects(
        session: Session,
        source_continuity_id: UUID,
        target_scope: EvolutionScope,
        mapped: dict[str, dict[UUID, UUID]],
        state: _EvolutionCopyState,
    ) -> None:
        """Copy terminal effects whose complete evidence history was copied.

        Args:
            session:
                Current atomic fork transaction.
            source_continuity_id:
                Source Storyline evolution owner.
            target_scope:
                Independent fork ownership.
            mapped:
                Structural source-to-target identifiers by row kind.
            state:
                Accumulated target history and normalized revisions.
        """

        effects = tuple(
            session.scalars(
                select(EvolutionEffectModel)
                .where(EvolutionEffectModel.continuity_id == source_continuity_id)
                .order_by(EvolutionEffectModel.created_at, EvolutionEffectModel.id)
                .with_for_update()
            )
        )
        for effect in effects:
            DbStorylineForkRepository._copy_evolution_effect(
                session, effect, target_scope, mapped, state
            )
        session.flush()

    @staticmethod
    def _copy_evolution_effect(
        session: Session,
        effect: EvolutionEffectModel,
        target_scope: EvolutionScope,
        mapped: dict[str, dict[UUID, UUID]],
        state: _EvolutionCopyState,
    ) -> None:
        """Remap and persist one eligible terminal evolution effect.

        Args:
            session:
                Current atomic fork transaction.
            effect:
                Source terminal effect candidate.
            target_scope:
                Independent fork ownership.
            mapped:
                Structural source-to-target identifiers by row kind.
            state:
                Accumulated target history and normalized revisions.

        Raises:
            StorylineForkConflictError:
                If applied audit history is internally incomplete.
        """

        if (
            effect.state == "reserved"
            or effect.proposal is None
            or effect.decision is None
        ):
            return

        source = EvolutionEvidenceReference.model_validate(effect.source)
        target_source = DbStorylineForkRepository._remap_evolution_source(
            source, target_scope, mapped
        )
        proposal = EvolutionProposal.model_validate(effect.proposal)
        commands = tuple(
            DbStorylineForkRepository._remap_evolution_command(
                command, target_scope, mapped
            )
            for command in proposal.commands
        )
        if target_source is None or any(command is None for command in commands):
            return

        target_commands = tuple(command for command in commands if command is not None)
        source_decision = EvolutionDecision.model_validate(effect.decision)
        source_events = source_decision.events
        if source_decision.outcome == EvolutionDecisionOutcome.APPLIED and len(
            source_events
        ) != len(target_commands):
            raise StorylineForkConflictError(
                "Applied evolution audit history is incomplete"
            )

        target_effect_id = uuid4()
        target_proposal_id = uuid4()
        expected_relationship_revision = state.relationship_revision
        expected_adaptation_revision = state.adaptation_revision
        event_commands = (
            target_commands
            if source_decision.outcome == EvolutionDecisionOutcome.APPLIED
            else ()
        )
        target_events = tuple(
            DbStorylineForkRepository._copy_evolution_event(
                source_event,
                command,
                target_proposal_id,
                target_scope,
                state,
            )
            for source_event, command in zip(source_events, event_commands, strict=True)
        )
        target_proposal = proposal.model_copy(
            update={
                "id": target_proposal_id,
                "scope": target_scope,
                "expected_relationship_revision": expected_relationship_revision,
                "expected_adaptation_revision": expected_adaptation_revision,
                "source": target_source,
                "commands": target_commands,
            }
        )
        target_decision = source_decision.model_copy(
            update={
                "proposal_id": target_proposal_id,
                "events": target_events,
            }
        )
        DbStorylineForkRepository._persist_evolution_effect(
            session,
            effect,
            target_effect_id,
            target_source,
            target_proposal,
            target_decision,
        )
        state.mappings.extend(
            (
                StorylineForkMapping(
                    kind="evolution_effect",
                    source_id=effect.id,
                    target_id=target_effect_id,
                ),
                StorylineForkMapping(
                    kind="evolution_proposal",
                    source_id=proposal.id,
                    target_id=target_proposal_id,
                ),
            )
        )

    @staticmethod
    def _copy_evolution_event(
        source_event: EvolutionEvent,
        command: EvolutionCommand,
        target_proposal_id: UUID,
        target_scope: EvolutionScope,
        state: _EvolutionCopyState,
    ) -> EvolutionEvent:
        """Remap one applied event and advance normalized target revisions.

        Args:
            source_event:
                Source inferred event.
            command:
                Fully remapped event command.
            target_proposal_id:
                Independent proposal identifier.
            target_scope:
                Independent fork ownership.
            state:
                Accumulated target history and normalized revisions.

        Returns:
            Independent remapped event.
        """

        relationship_revision, adaptation_revision = state.advance(command)
        target_event = source_event.model_copy(
            update={
                "id": uuid4(),
                "proposal_id": target_proposal_id,
                "scope": target_scope,
                "command": command,
                "relationship_revision": relationship_revision,
                "adaptation_revision": adaptation_revision,
            }
        )
        state.events.append(target_event)
        state.event_ids[source_event.id] = target_event.id
        state.events_by_id[target_event.id] = target_event
        state.mappings.append(
            StorylineForkMapping(
                kind="evolution_event",
                source_id=source_event.id,
                target_id=target_event.id,
            )
        )
        return target_event

    @staticmethod
    def _persist_evolution_effect(
        session: Session,
        source_effect: EvolutionEffectModel,
        target_effect_id: UUID,
        target_source: EvolutionEvidenceReference,
        target_proposal: EvolutionProposal,
        target_decision: EvolutionDecision,
    ) -> None:
        """Persist one fully remapped terminal effect and its inferred events.

        Args:
            session:
                Current atomic fork transaction.
            source_effect:
                Source audit row supplying timestamps and terminal state.
            target_effect_id:
                Independent target effect identifier.
            target_source:
                Remapped exact source checkpoint.
            target_proposal:
                Remapped terminal proposal.
            target_decision:
                Remapped terminal decision and events.
        """

        scope = target_proposal.scope
        session.add(
            EvolutionEffectModel(
                id=target_effect_id,
                continuity_id=scope.continuity_id,
                identity_id=scope.identity_id,
                persona_id=scope.persona_id,
                conversation_id=target_source.conversation_id,
                source_persona_message_id=target_source.persona_message_id,
                source=target_source.model_dump(mode="json"),
                state=source_effect.state,
                provenance=deepcopy(source_effect.provenance),
                proposal=target_proposal.model_dump(mode="json"),
                decision=target_decision.model_dump(mode="json"),
                created_at=source_effect.created_at,
                completed_at=source_effect.completed_at,
            )
        )
        for position, event in enumerate(target_decision.events, start=1):
            session.add(
                EvolutionEventModel(
                    id=event.id,
                    effect_id=target_effect_id,
                    proposal_id=event.proposal_id,
                    continuity_id=scope.continuity_id,
                    identity_id=scope.identity_id,
                    persona_id=scope.persona_id,
                    position=position,
                    command=event.command.model_dump(mode="json"),
                    relationship_revision=event.relationship_revision,
                    adaptation_revision=event.adaptation_revision,
                    provenance=event.provenance.model_dump(mode="json"),
                    created_at=event.created_at,
                )
            )

    @staticmethod
    def _copy_evolution_corrections(
        session: Session,
        source_continuity_id: UUID,
        target_scope: EvolutionScope,
        mapped: dict[str, dict[UUID, UUID]],
        state: _EvolutionCopyState,
    ) -> None:
        """Copy corrections whose inferred targets and evidence were copied.

        Args:
            session:
                Current atomic fork transaction.
            source_continuity_id:
                Source Storyline evolution owner.
            target_scope:
                Independent fork ownership.
            mapped:
                Structural source-to-target identifiers by row kind.
            state:
                Accumulated target history and normalized revisions.
        """

        corrections = tuple(
            session.scalars(
                select(EvolutionCorrectionEventModel)
                .where(
                    EvolutionCorrectionEventModel.continuity_id == source_continuity_id
                )
                .order_by(
                    EvolutionCorrectionEventModel.relationship_revision
                    + EvolutionCorrectionEventModel.adaptation_revision,
                    EvolutionCorrectionEventModel.id,
                )
                .with_for_update()
            )
        )
        for correction in corrections:
            DbStorylineForkRepository._copy_evolution_correction(
                session, correction, target_scope, mapped, state
            )

    @staticmethod
    def _copy_evolution_correction(
        session: Session,
        row: EvolutionCorrectionEventModel,
        target_scope: EvolutionScope,
        mapped: dict[str, dict[UUID, UUID]],
        state: _EvolutionCopyState,
    ) -> None:
        """Remap and persist one correction of a copied inferred event.

        Args:
            session:
                Current atomic fork transaction.
            row:
                Source correction candidate.
            target_scope:
                Independent fork ownership.
            mapped:
                Structural source-to-target identifiers by row kind.
            state:
                Accumulated target history and normalized revisions.
        """

        target_event_id = state.event_ids.get(row.target_event_id)
        if target_event_id is None:
            return
        replacement = (
            _EVOLUTION_COMMAND_ADAPTER.validate_python(row.replacement)
            if row.replacement is not None
            else None
        )
        if replacement is not None:
            replacement = DbStorylineForkRepository._remap_evolution_command(
                replacement, target_scope, mapped
            )
            if replacement is None:
                return

        expected_relationship_revision = state.relationship_revision
        expected_adaptation_revision = state.adaptation_revision
        target_event = state.events_by_id[target_event_id]
        relationship_revision, adaptation_revision = state.advance(target_event.command)
        correction = EvolutionCorrectionEvent(
            id=uuid4(),
            scope=target_scope,
            target_event_id=target_event_id,
            action=EvolutionCorrectionAction(row.action),
            replacement=replacement,
            note=row.note,
            expected_relationship_revision=expected_relationship_revision,
            expected_adaptation_revision=expected_adaptation_revision,
            relationship_revision=relationship_revision,
            adaptation_revision=adaptation_revision,
            created_at=row.created_at,
        )
        state.corrections.append(correction)
        session.add(
            EvolutionCorrectionEventModel(
                id=correction.id,
                continuity_id=target_scope.continuity_id,
                identity_id=target_scope.identity_id,
                persona_id=target_scope.persona_id,
                target_event_id=target_event_id,
                action=correction.action.value,
                replacement=(
                    correction.replacement.model_dump(mode="json")
                    if correction.replacement is not None
                    else None
                ),
                note=correction.note,
                expected_relationship_revision=expected_relationship_revision,
                expected_adaptation_revision=expected_adaptation_revision,
                relationship_revision=relationship_revision,
                adaptation_revision=adaptation_revision,
                created_at=correction.created_at,
            )
        )
        state.mappings.append(
            StorylineForkMapping(
                kind="evolution_correction",
                source_id=row.id,
                target_id=correction.id,
            )
        )

    @staticmethod
    def _persist_evolution_projections(
        session: Session,
        source_continuity_id: UUID,
        target_scope: EvolutionScope,
        starting_relationship: StartingRelationship,
        state: _EvolutionCopyState,
    ) -> None:
        """Replay copied history and persist independent projection caches.

        Args:
            session:
                Current atomic fork transaction.
            source_continuity_id:
                Source projection identifier recorded in fork mappings.
            target_scope:
                Independent fork ownership.
            starting_relationship:
                Copied user-authored starting relationship.
            state:
                Complete copied history and normalized final revisions.
        """

        relationship, adaptations, relationship_checkpoint, adaptation_checkpoint = (
            DbStorylineForkRepository._replay_copied_evolution(
                target_scope,
                starting_relationship,
                tuple(state.events),
                tuple(state.corrections),
                state.relationship_revision,
                state.adaptation_revision,
            )
        )
        updated_at = datetime.now(UTC)
        session.add_all(
            [
                RelationshipProjectionModel(
                    continuity_id=target_scope.continuity_id,
                    identity_id=target_scope.identity_id,
                    persona_id=target_scope.persona_id,
                    revision=relationship.revision,
                    rebuild_checkpoint_id=relationship_checkpoint,
                    snapshot=relationship.model_dump(mode="json"),
                    updated_at=updated_at,
                ),
                PersonaAdaptationProjectionModel(
                    continuity_id=target_scope.continuity_id,
                    identity_id=target_scope.identity_id,
                    persona_id=target_scope.persona_id,
                    revision=adaptations.revision,
                    rebuild_checkpoint_id=adaptation_checkpoint,
                    snapshot=adaptations.model_dump(mode="json"),
                    updated_at=updated_at,
                ),
            ]
        )
        state.mappings.extend(
            (
                StorylineForkMapping(
                    kind="relationship_projection",
                    source_id=source_continuity_id,
                    target_id=target_scope.continuity_id,
                ),
                StorylineForkMapping(
                    kind="persona_adaptation_projection",
                    source_id=source_continuity_id,
                    target_id=target_scope.continuity_id,
                ),
            )
        )

    @staticmethod
    def _remap_evolution_source(
        source: EvolutionEvidenceReference,
        target_scope: EvolutionScope,
        mapped: dict[str, dict[UUID, UUID]],
    ) -> EvolutionEvidenceReference | None:
        """Remap one exact evidence reference when all owned rows were copied.

        Args:
            source:
                Source-continuity evidence reference.
            target_scope:
                Independent fork ownership.
            mapped:
                Structural source-to-target identifiers by row kind.

        Returns:
            Remapped evidence, or None when its history was not copied.
        """

        conversation_id = mapped["conversation"].get(source.conversation_id)
        user_message_id = mapped["message"].get(source.user_message_id)
        persona_message_id = mapped["message"].get(source.persona_message_id)
        scene_id = (
            mapped["scene"].get(source.scene_id)
            if source.scene_id is not None
            else None
        )
        if (
            conversation_id is None
            or user_message_id is None
            or persona_message_id is None
            or (source.scene_id is not None and scene_id is None)
        ):
            return None

        return source.model_copy(
            update={
                "scope": target_scope,
                "conversation_id": conversation_id,
                "scene_id": scene_id,
                "user_message_id": user_message_id,
                "persona_message_id": persona_message_id,
            }
        )

    @staticmethod
    def _remap_evolution_command(
        command: EvolutionCommand,
        target_scope: EvolutionScope,
        mapped: dict[str, dict[UUID, UUID]],
    ) -> EvolutionCommand | None:
        """Remap every evidence source of one atomic command.

        Args:
            command:
                Source-continuity typed command.
            target_scope:
                Independent fork ownership.
            mapped:
                Structural source-to-target identifiers by row kind.

        Returns:
            Remapped command, or None when any supporting turn was not copied.
        """

        sources = tuple(
            DbStorylineForkRepository._remap_evolution_source(
                source, target_scope, mapped
            )
            for source in command.sources
        )
        if any(source is None for source in sources):
            return None
        return command.model_copy(
            update={
                "sources": tuple(source for source in sources if source is not None)
            }
        )

    @staticmethod
    def _replay_copied_evolution(
        scope: EvolutionScope,
        starting: StartingRelationship,
        events: tuple[EvolutionEvent, ...],
        corrections: tuple[EvolutionCorrectionEvent, ...],
        relationship_revision: int,
        adaptation_revision: int,
    ) -> tuple[
        RelationshipProjection,
        PersonaAdaptationProjection,
        UUID | None,
        UUID | None,
    ]:
        """Replay copied history from the user-authored starting state.

        Args:
            scope:
                Independent fork ownership.
            starting:
                Copied user-selected starting relationship.
            events:
                Eligible remapped inferred events.
            corrections:
                Remapped user-authored interpretations.
            relationship_revision:
                Normalized final relationship audit revision.
            adaptation_revision:
                Normalized final adaptation audit revision.

        Returns:
            Both rebuilt caches and their last inferred checkpoints.
        """

        dispositions: dict[UUID, EvolutionCommand | None] = {}
        for correction in corrections:
            if correction.action == EvolutionCorrectionAction.RESTORE:
                dispositions.pop(correction.target_event_id, None)
            elif correction.action == EvolutionCorrectionAction.EXCLUDE:
                dispositions[correction.target_event_id] = None
            else:
                dispositions[correction.target_event_id] = correction.replacement

        relationship = RelationshipProjection(
            scope=scope,
            revision=0,
            social=RelationshipSocialStatus(starting.social),
            romantic=RelationshipRomanticStatus(starting.romantic),
            dynamic=RelationshipDynamic(starting.dynamic),
            trust=RelationshipTrust(starting.trust),
            affection=RelationshipAffection(starting.affection),
        )
        adaptations = PersonaAdaptationProjection(scope=scope, revision=0)
        relationship_checkpoint: UUID | None = None
        adaptation_checkpoint: UUID | None = None
        for event in events:
            if is_adaptation_command(event.command):
                adaptation_checkpoint = event.id
            else:
                relationship_checkpoint = event.id
            command = dispositions.get(event.id, event.command)
            if command is not None:
                relationship, adaptations = apply_evolution_command(
                    relationship, adaptations, command
                )

        return (
            relationship.model_copy(update={"revision": relationship_revision}),
            adaptations.model_copy(update={"revision": adaptation_revision}),
            relationship_checkpoint,
            adaptation_checkpoint,
        )

    @staticmethod
    def _copy_summaries(
        session: Session,
        source_conversation: ConversationModel,
        target_conversation: ConversationModel,
        message_ids: dict[UUID, UUID],
    ) -> list[StorylineForkMapping]:
        """Copy only summary lineage whose checkpoints and predecessors exist.

        Args:
            session:
                Current transaction.
            source_conversation:
                Source scene conversation.
            target_conversation:
                Independent copied conversation.
            message_ids:
                Copied selected-path message mapping.

        Returns:
            Summary identifier mappings in lineage order.
        """

        rows = tuple(
            session.scalars(
                select(SummaryRevisionModel)
                .where(
                    SummaryRevisionModel.conversation_id == source_conversation.id,
                    SummaryRevisionModel.continuity_id
                    == source_conversation.continuity_id,
                    SummaryRevisionModel.checkpoint_message_id.in_(message_ids),
                )
                .order_by(SummaryRevisionModel.revision, SummaryRevisionModel.id)
            )
        )
        summary_ids: dict[UUID, UUID] = {}
        mappings: list[StorylineForkMapping] = []
        for row in rows:
            if row.predecessor_id is not None and row.predecessor_id not in summary_ids:
                continue
            target_id = uuid4()
            summary_ids[row.id] = target_id
            session.add(
                SummaryRevisionModel(
                    id=target_id,
                    conversation_id=target_conversation.id,
                    continuity_id=target_conversation.continuity_id,
                    revision=row.revision,
                    predecessor_id=(
                        None
                        if row.predecessor_id is None
                        else summary_ids[row.predecessor_id]
                    ),
                    checkpoint_message_id=message_ids[row.checkpoint_message_id],
                    content=row.content,
                    generation=deepcopy(row.generation),
                    created_at=row.created_at,
                )
            )
            mappings.append(
                StorylineForkMapping(
                    kind="summary", source_id=row.id, target_id=target_id
                )
            )
        session.flush()
        return mappings

    @staticmethod
    def _path(
        session: Session, conversation: ConversationModel, leaf_id: UUID
    ) -> tuple[MessageModel, ...]:
        """Resolve one exact root-to-persona ancestry under source ownership.

        Args:
            session:
                Current transaction.
            conversation:
                Owned source conversation.
            leaf_id:
                Exact selected leaf or persona branch point.

        Returns:
            Root-to-leaf source message rows.
        """

        rows = tuple(
            session.scalars(
                select(MessageModel).where(
                    MessageModel.conversation_id == conversation.id,
                    MessageModel.continuity_id == conversation.continuity_id,
                )
            )
        )
        by_id = {row.id: row for row in rows}
        leaf = by_id.get(leaf_id)
        if leaf is None:
            raise StorylineForkConflictError("Fork target is not source-owned")

        reversed_path = [leaf]
        while reversed_path[-1].parent_id is not None:
            parent = by_id.get(reversed_path[-1].parent_id)
            if parent is None:
                raise StorylineForkConflictError("Source graph ancestry is incomplete")
            reversed_path.append(parent)

        return tuple(reversed(reversed_path))

    @staticmethod
    def _conversation(session: Session, scene: SceneModel) -> ConversationModel:
        """Load a scene's completely owned conversation.

        Args:
            session:
                Current transaction.
            scene:
                Locked source scene.

        Returns:
            Owned conversation row.
        """

        row = session.scalar(
            select(ConversationModel)
            .where(
                ConversationModel.id == scene.conversation_id,
                ConversationModel.continuity_id == scene.continuity_id,
                ConversationModel.identity_id == scene.identity_id,
                ConversationModel.persona_id == scene.persona_id,
                ConversationModel.mode == "storyline",
            )
            .with_for_update()
        )
        if row is None:
            raise StorylineForkConflictError("Source conversation ownership changed")

        return row

    @staticmethod
    def _identity(session: Session, identity_id: UUID, lock: bool) -> IdentityModel:
        """Load one identity, optionally locked.

        Args:
            session:
                Current transaction.
            identity_id:
                Required identity identifier.
            lock:
                Whether to lock the profile row.

        Returns:
            Persisted identity row.
        """

        statement = select(IdentityModel).where(IdentityModel.id == identity_id)
        row = session.scalar(statement.with_for_update() if lock else statement)
        if row is None:
            raise StorylineForkConflictError("Reviewed identity no longer exists")

        return row

    @staticmethod
    def _persona(session: Session, persona_id: UUID, lock: bool) -> PersonaModel:
        """Load one persona, optionally locked.

        Args:
            session:
                Current transaction.
            persona_id:
                Required persona identifier.
            lock:
                Whether to lock the profile row.

        Returns:
            Persisted persona row.
        """

        statement = select(PersonaModel).where(PersonaModel.id == persona_id)
        row = session.scalar(statement.with_for_update() if lock else statement)
        if row is None:
            raise StorylineForkConflictError("Reviewed persona no longer exists")

        return row

    @staticmethod
    def _require_identity_snapshot(row: IdentityModel, expected: Identity) -> None:
        """Reject any identity revision or authored-field change after review.

        Args:
            row:
                Locked current identity row.
            expected:
                Reviewed identity domain snapshot.
        """

        snapshot = DbStorylineForkRepository._identity_snapshot(row)
        if snapshot != expected:
            raise StorylineForkConflictError("Reviewed identity changed")

    @staticmethod
    def _require_persona_snapshot(row: PersonaModel, expected: Persona) -> None:
        """Reject any persona revision or authored-field change after review.

        Args:
            row:
                Locked current persona row.
            expected:
                Reviewed persona domain snapshot.
        """

        snapshot = DbStorylineForkRepository._persona_snapshot(row)
        if snapshot != expected:
            raise StorylineForkConflictError("Reviewed persona changed")

    @staticmethod
    def _identity_snapshot(row: IdentityModel) -> Identity:
        """Build the repository's identity domain snapshot.

        Args:
            row:
                Persisted identity row.

        Returns:
            Detached identity snapshot.
        """

        return DbIdentityRepository._snapshot(row)

    @staticmethod
    def _persona_snapshot(row: PersonaModel) -> Persona:
        """Build the repository's persona domain snapshot.

        Args:
            row:
                Persisted persona row.

        Returns:
            Detached persona snapshot.
        """

        return DbPersonaRepository._snapshot(row)

    @staticmethod
    def _confirmation(
        session: Session, preview: StorylineForkPreview
    ) -> ContinuityModel | None:
        """Resolve confirmation equality against the entire reviewed preview.

        Args:
            session:
                Current session.
            preview:
                Submitted fork confirmation.

        Returns:
            Existing target continuity, or None.
        """

        row = session.scalar(
            select(ContinuityModel).where(
                ContinuityModel.request_id == preview.request_id
            )
        )
        if row is not None and row.confirmed_request != preview.model_dump(mode="json"):
            raise ConfirmationConflictError(
                "Use a new fork confirmation identifier for changed inputs"
            )

        if row is not None and row.mode != "storyline":
            raise ConfirmationConflictError(
                "The confirmation identifier belongs to another operation"
            )

        return row

    @staticmethod
    def _result(session: Session, continuity: ContinuityModel) -> StorylineForkResult:
        """Rebuild a committed fork result from durable provenance.

        Args:
            session:
                Current session.
            continuity:
                Idempotently resolved fork continuity.

        Returns:
            Detached structural fork result.
        """

        storyline = session.scalars(
            select(StorylineModel).where(StorylineModel.continuity_id == continuity.id)
        ).one()
        scenes = tuple(
            session.scalars(
                select(SceneModel)
                .where(SceneModel.continuity_id == continuity.id)
                .order_by(SceneModel.position)
            )
        )
        provenance = storyline.fork_provenance or {}
        mappings = tuple(
            StorylineForkMapping.model_validate(value)
            for value in provenance.get("mappings", [])
        )
        if not mappings:
            raise StorylineForkConflictError(
                "Confirmed continuity is not a structural Storyline fork"
            )

        return StorylineForkResult(
            storyline=DbStorylineRepository._snapshot(session, storyline),
            scenes=tuple(
                DbStorylineRepository._scene_snapshot(scene) for scene in scenes
            ),
            mappings=mappings,
        )
