"""Transactional Storyline memory lineage and extraction persistence."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    ChangeMemoryStateCommand,
    ConversationScope,
    CorrectMemoryCommand,
    CreateMemoryCommand,
    DeleteMemoryCommand,
    DismissMemoryConflictCommand,
    ExtractionEffect,
    ExtractionEffectConflictError,
    ExtractionEffectState,
    ExtractionProvenance,
    InvalidMemoryDeltaTargetError,
    InvalidTemporalProvenanceError,
    MemoryAuthorship,
    MemoryConflict,
    MemoryConflictNotFoundError,
    MemoryConflictState,
    MemoryDelta,
    MemoryEvidence,
    MemoryNotFoundError,
    MemoryRevision,
    MemoryRevisionKind,
    MemoryRevisionState,
    MemorySubjectConflictError,
    ProtectedMemoryCorrectionError,
    RecordMemoryConflictCommand,
    ReinforceMemoryCommand,
    ScenePosition,
    StaleMemoryConflictError,
    StaleMemoryRevisionError,
    StorylineMemory,
    SupersedeMemoryCommand,
)
from chat_buddy.characters.infrastructure.db.models import (
    ContinuityModel,
    ConversationModel,
    MemoryConflictModel,
    MemoryEvidenceModel,
    MemoryExtractionEffectModel,
    MemoryRevisionModel,
    MessageModel,
    SceneModel,
    StorylineMemoryModel,
)


class DbStorylineMemoryRepository:
    """Read Storyline memory lineages and perform guarded hard deletion."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory:
                Factory used for short database transactions.
        """

        self._factory = session_factory

    def get(self, continuity_id: UUID, memory_id: UUID) -> StorylineMemory:
        """Read a complete lineage within its expected Storyline.

        Args:
            continuity_id:
                Expected Storyline owner.
            memory_id:
                Logical-memory identifier.

        Returns:
            Complete detached memory lineage.

        Raises:
            MemoryNotFoundError:
                If the memory is absent or foreign.
        """

        with self._factory() as session:
            row = self._owned(session, continuity_id, memory_id)
            return self._snapshot(session, row)

    def list(self, continuity_id: UUID) -> tuple[StorylineMemory, ...]:
        """List a Storyline's memories deterministically by subject and identifier.

        Args:
            continuity_id:
                Expected Storyline owner.

        Returns:
            Complete detached memory lineages.
        """

        with self._factory() as session:
            rows = tuple(
                session.scalars(
                    select(StorylineMemoryModel)
                    .where(StorylineMemoryModel.continuity_id == continuity_id)
                    .order_by(StorylineMemoryModel.subject_key, StorylineMemoryModel.id)
                )
            )

            return tuple(self._snapshot(session, row) for row in rows)

    def list_eligible(
        self,
        continuity_id: UUID,
        target_scene_position: int,
        selected_persona_message_ids: frozenset[UUID],
    ) -> tuple[StorylineMemory, ...]:
        """List active memories whose current source is branch- and time-eligible.

        Args:
            continuity_id:
                Expected Storyline owner.
            target_scene_position:
                Positive target scene position.
            selected_persona_message_ids:
                Persona checkpoints on the selected histories.

        Returns:
            Eligible complete lineages in deterministic order.
        """

        if target_scene_position < 1:
            raise InvalidTemporalProvenanceError(
                "Target scene position must be positive"
            )

        return tuple(
            memory
            for memory in self.list(continuity_id)
            if memory.current.state == MemoryRevisionState.ACTIVE
            and memory.current.source.persona_message_id in selected_persona_message_ids
            and memory.current.source.occurrence.position <= target_scene_position
            and memory.current.source.learned.position <= target_scene_position
        )

    def correct(self, command: CorrectMemoryCommand) -> StorylineMemory:
        """Add a guarded user-authored correction to an active lineage.

        Args:
            command:
                Guarded correction request.

        Returns:
            Updated complete memory lineage.

        Raises:
            MemoryNotFoundError:
                If the memory is absent or foreign.
            StaleMemoryRevisionError:
                If the observed revision is no longer current.
            ProtectedMemoryCorrectionError:
                If the memory is currently excluded.
            MemorySubjectConflictError:
                If another memory owns the corrected subject.
        """

        try:
            with self._factory() as session, session.begin():
                row, current = self._locked_current(session, command)
                if current.state == MemoryRevisionState.EXCLUDED:
                    raise ProtectedMemoryCorrectionError(
                        "Reactivate an excluded memory before correcting it"
                    )

                self._append_revision(
                    session,
                    row,
                    current,
                    subject=command.subject,
                    content=command.content,
                    state=MemoryRevisionState.ACTIVE,
                    authorship=MemoryAuthorship.USER,
                    kind=MemoryRevisionKind.USER_CORRECTION,
                )
                row.subject_key = command.subject.casefold()
                session.flush()

                return self._snapshot(session, row)
        except IntegrityError as error:
            if "subject" in str(error).lower():
                raise MemorySubjectConflictError(
                    "Another memory already owns the corrected subject"
                ) from error

            raise StaleMemoryRevisionError(
                "Memory changed while the correction was committed"
            ) from error

    def change_state(self, command: ChangeMemoryStateCommand) -> StorylineMemory:
        """Add a guarded exclusion or reactivation revision.

        Args:
            command:
                Guarded lifecycle transition.

        Returns:
            Updated complete memory lineage.

        Raises:
            MemoryNotFoundError:
                If the memory is absent or foreign.
            StaleMemoryRevisionError:
                If the observed revision or requested transition is stale.
        """

        try:
            with self._factory() as session, session.begin():
                row, current = self._locked_current(session, command)
                excluding = command.operation == "exclude"
                expected_state = (
                    MemoryRevisionState.ACTIVE
                    if excluding
                    else MemoryRevisionState.EXCLUDED
                )
                if current.state != expected_state:
                    raise StaleMemoryRevisionError(
                        f"Memory cannot be changed with {command.operation!r} "
                        f"from {current.state!r}"
                    )

                self._append_revision(
                    session,
                    row,
                    current,
                    subject=current.subject,
                    content=current.content,
                    state=(
                        MemoryRevisionState.EXCLUDED
                        if excluding
                        else MemoryRevisionState.ACTIVE
                    ),
                    authorship=MemoryAuthorship(current.authorship),
                    kind=(
                        MemoryRevisionKind.EXCLUSION
                        if excluding
                        else MemoryRevisionKind.REACTIVATION
                    ),
                )
                session.flush()

                return self._snapshot(session, row)
        except IntegrityError as error:
            raise StaleMemoryRevisionError(
                "Memory changed while the lifecycle transition was committed"
            ) from error

    def delete(self, command: DeleteMemoryCommand) -> None:
        """Hard-delete one guarded lineage and its dependent conflict evidence.

        Args:
            command:
                Guarded hard-deletion request.

        Raises:
            MemoryNotFoundError:
                If the memory is absent or foreign.
            StaleMemoryRevisionError:
                If its current revision changed.
        """

        with self._factory() as session, session.begin():
            row = session.scalar(
                select(StorylineMemoryModel)
                .where(
                    StorylineMemoryModel.id == command.memory_id,
                    StorylineMemoryModel.continuity_id == command.continuity_id,
                )
                .with_for_update()
            )
            if row is None:
                raise MemoryNotFoundError(str(command.memory_id))

            if row.current_revision_id != command.expected_revision_id:
                raise StaleMemoryRevisionError(
                    "Memory changed after the deletion was reviewed"
                )

            conflict_evidence_ids = tuple(
                session.scalars(
                    select(MemoryConflictModel.evidence_id).where(
                        MemoryConflictModel.memory_id == row.id
                    )
                )
            )
            session.execute(
                delete(MemoryConflictModel).where(
                    MemoryConflictModel.memory_id == row.id
                )
            )
            if conflict_evidence_ids:
                session.execute(
                    delete(MemoryEvidenceModel).where(
                        MemoryEvidenceModel.id.in_(conflict_evidence_ids)
                    )
                )
            row.current_revision_id = None
            session.flush()
            session.delete(row)

    @staticmethod
    def _locked_current(
        session: Session,
        command: CorrectMemoryCommand | ChangeMemoryStateCommand,
    ) -> tuple[StorylineMemoryModel, MemoryRevisionModel]:
        """Lock and validate the current revision named by a command.

        Args:
            session:
                Current transaction.
            command:
                Guarded management request.

        Returns:
            Locked logical memory and current revision.

        Raises:
            MemoryNotFoundError:
                If the memory is absent or foreign.
            StaleMemoryRevisionError:
                If the current revision changed.
        """

        row = session.scalar(
            select(StorylineMemoryModel)
            .where(
                StorylineMemoryModel.id == command.memory_id,
                StorylineMemoryModel.continuity_id == command.continuity_id,
            )
            .with_for_update()
        )
        if row is None:
            raise MemoryNotFoundError(str(command.memory_id))
        if row.current_revision_id != command.expected_revision_id:
            raise StaleMemoryRevisionError(
                "Memory changed after the operation was reviewed"
            )

        current = session.get(MemoryRevisionModel, row.current_revision_id)
        if current is None or current.state == MemoryRevisionState.SUPERSEDED:
            raise StaleMemoryRevisionError("Memory has no matching current revision")

        return row, current

    @staticmethod
    def _append_revision(
        session: Session,
        row: StorylineMemoryModel,
        current: MemoryRevisionModel,
        *,
        subject: str,
        content: str,
        state: MemoryRevisionState,
        authorship: MemoryAuthorship,
        kind: MemoryRevisionKind,
    ) -> None:
        """Supersede the current row and append one immutable revision.

        Args:
            session:
                Current transaction.
            row:
                Locked logical memory.
            current:
                Locked current revision.
            subject:
                Subject retained or supplied by the operation.
            content:
                Content retained or supplied by the operation.
            state:
                New current lifecycle state.
            authorship:
                New current content authority.
            kind:
                Revision operation kind.
        """

        current.state = MemoryRevisionState.SUPERSEDED.value
        session.flush()

        revision_id = uuid4()
        session.add(
            MemoryRevisionModel(
                id=revision_id,
                memory_id=row.id,
                continuity_id=row.continuity_id,
                revision=current.revision + 1,
                predecessor_id=current.id,
                subject=subject,
                content=content,
                state=state.value,
                authorship=authorship.value,
                kind=kind.value,
                source_evidence_id=current.source_evidence_id,
                created_at=datetime.now(UTC),
            )
        )
        session.flush()
        row.current_revision_id = revision_id

    @staticmethod
    def _owned(
        session: Session, continuity_id: UUID, memory_id: UUID
    ) -> StorylineMemoryModel:
        """Return one owned row or raise the domain absence error.

        Args:
            session:
                Current database session.
            continuity_id:
                Expected Storyline owner.
            memory_id:
                Logical-memory identifier.

        Returns:
            Owned persistence row.

        Raises:
            MemoryNotFoundError:
                If no row matches both identifiers.
        """

        row = session.scalar(
            select(StorylineMemoryModel).where(
                StorylineMemoryModel.id == memory_id,
                StorylineMemoryModel.continuity_id == continuity_id,
            )
        )
        if row is None:
            raise MemoryNotFoundError(str(memory_id))

        return row

    @classmethod
    def _snapshot(cls, session: Session, row: StorylineMemoryModel) -> StorylineMemory:
        """Build a validated complete domain lineage.

        Args:
            session:
                Current database session.
            row:
                Logical-memory persistence row.

        Returns:
            Detached immutable domain memory.
        """

        evidence_rows = tuple(
            session.scalars(
                select(MemoryEvidenceModel)
                .where(
                    MemoryEvidenceModel.memory_id == row.id,
                    MemoryEvidenceModel.purpose == "support",
                )
                .order_by(MemoryEvidenceModel.created_at, MemoryEvidenceModel.id)
            )
        )
        evidence = {
            item.id: DbMemoryExtractionRepository._evidence_snapshot(item)
            for item in evidence_rows
        }
        revisions = tuple(
            session.scalars(
                select(MemoryRevisionModel)
                .where(MemoryRevisionModel.memory_id == row.id)
                .order_by(MemoryRevisionModel.revision)
            )
        )

        return StorylineMemory(
            id=row.id,
            continuity_id=row.continuity_id,
            current_revision_id=_required_current(row),
            revisions=tuple(
                MemoryRevision(
                    id=revision.id,
                    memory_id=revision.memory_id,
                    continuity_id=revision.continuity_id,
                    revision=revision.revision,
                    predecessor_id=revision.predecessor_id,
                    subject=revision.subject,
                    content=revision.content,
                    state=MemoryRevisionState(revision.state),
                    authorship=MemoryAuthorship(revision.authorship),
                    kind=MemoryRevisionKind(revision.kind),
                    source=evidence[revision.source_evidence_id],
                    created_at=_aware(revision.created_at),
                )
                for revision in revisions
            ),
            evidence=tuple(evidence.values()),
        )


class DbMemoryExtractionRepository:
    """Reserve and atomically persist validated Storyline extraction deltas."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory:
                Factory used for short database transactions.
        """

        self._factory = session_factory

    def reserve(
        self, scope: ConversationScope, scene_id: UUID, source_persona_message_id: UUID
    ) -> ExtractionEffect:
        """Reserve or return the sole eligible effect for a source checkpoint.

        Args:
            scope:
                Complete source ownership.
            scene_id:
                Source scene identifier.
            source_persona_message_id:
                Complete selected persona checkpoint.

        Returns:
            Existing or newly reserved effect.

        Raises:
            ExtractionEffectConflictError:
                If source ownership, lifecycle, selection, or turn shape is invalid.
        """

        try:
            with self._factory() as session, session.begin():
                existing = self._effect_row(session, scope, source_persona_message_id)
                if existing is not None:
                    return self._effect_snapshot(existing)

                self._validate_reservation(
                    session, scope, scene_id, source_persona_message_id
                )

                now = datetime.now(UTC)
                row = MemoryExtractionEffectModel(
                    continuity_id=scope.continuity_id,
                    identity_id=scope.identity_id,
                    persona_id=scope.persona_id,
                    conversation_id=scope.conversation_id,
                    mode="storyline",
                    scene_id=scene_id,
                    source_persona_message_id=source_persona_message_id,
                    state=ExtractionEffectState.RESERVED.value,
                    created_at=now,
                )
                session.add(row)
                session.flush()

                return self._effect_snapshot(row)
        except IntegrityError as error:
            with self._factory() as session:
                existing = self._effect_row(session, scope, source_persona_message_id)
                if existing is not None:
                    return self._effect_snapshot(existing)

            raise ExtractionEffectConflictError(
                "The source checkpoint could not be reserved"
            ) from error

    def get_effect(
        self, scope: ConversationScope, source_persona_message_id: UUID
    ) -> ExtractionEffect | None:
        """Read an owned extraction effect when one exists.

        Args:
            scope:
                Complete source ownership.
            source_persona_message_id:
                Source persona checkpoint.

        Returns:
            Detached effect or None.
        """

        with self._factory() as session:
            row = self._effect_row(session, scope, source_persona_message_id)
            return None if row is None else self._effect_snapshot(row)

    def apply(
        self,
        effect_id: UUID,
        delta: MemoryDelta,
        provenance: ExtractionProvenance,
    ) -> ExtractionEffect:
        """Atomically apply a validated delta and finish its reserved effect.

        Args:
            effect_id:
                Reserved extraction effect.
            delta:
                Fully application-validated structured proposal.
            provenance:
                Complete immutable extraction configuration.

        Returns:
            Terminal extraction effect.

        Raises:
            ExtractionEffectConflictError:
                If the effect is absent, terminal, or mismatched.
            InvalidMemoryDeltaTargetError:
                If a target changed before commit.
        """

        try:
            with self._factory() as session, session.begin():
                effect = session.scalar(
                    select(MemoryExtractionEffectModel)
                    .where(MemoryExtractionEffectModel.id == effect_id)
                    .with_for_update()
                )
                if effect is None or effect.state != ExtractionEffectState.RESERVED:
                    raise ExtractionEffectConflictError(
                        "Extraction effect is absent or already terminal"
                    )

                if (
                    _scope(effect) != delta.scope
                    or effect.source_persona_message_id
                    != delta.source_persona_message_id
                    or delta.extractor != provenance.extractor
                ):
                    raise ExtractionEffectConflictError(
                        "Delta does not match the reserved extraction source"
                    )

                self._validate_reservation(
                    session,
                    delta.scope,
                    effect.scene_id,
                    effect.source_persona_message_id,
                )

                if delta.commands[0].operation == "no_change":
                    effect.state = ExtractionEffectState.NO_CHANGE.value
                else:
                    for command in delta.commands:
                        if command.operation == "no_change":
                            continue
                        if command.evidence.extraction != provenance:
                            raise InvalidTemporalProvenanceError(
                                "Command evidence uses different extraction provenance"
                            )

                        if command.operation == "create":
                            self._create(session, effect, command)
                        elif command.operation == "reinforce":
                            self._reinforce(session, effect, command)
                        elif command.operation == "supersede":
                            self._supersede(session, effect, command)
                        elif command.operation == "conflict":
                            self._conflict(session, effect, command)
                    effect.state = ExtractionEffectState.APPLIED.value

                effect.selection_id = delta.selection_id
                effect.provenance = provenance.model_dump(mode="json")
                effect.completed_at = datetime.now(UTC)
                session.flush()

                return self._effect_snapshot(effect)
        except IntegrityError as error:
            message = str(error).lower()
            if "subject" in message:
                raise MemorySubjectConflictError(
                    "A logical memory already owns the normalized subject"
                ) from error

            if "evidence" in message:
                raise InvalidMemoryDeltaTargetError(
                    "Evidence or its source turn is duplicated or foreign"
                ) from error

            raise InvalidMemoryDeltaTargetError(
                "The validated delta conflicts with current persistence state"
            ) from error

    def list_conflicts(self, continuity_id: UUID) -> tuple[MemoryConflict, ...]:
        """List all conflicts for one Storyline in stable creation order.

        Args:
            continuity_id:
                Expected Storyline owner.

        Returns:
            Detached conflict snapshots.
        """

        with self._factory() as session:
            rows = tuple(
                session.scalars(
                    select(MemoryConflictModel)
                    .where(MemoryConflictModel.continuity_id == continuity_id)
                    .order_by(MemoryConflictModel.created_at, MemoryConflictModel.id)
                )
            )

            return tuple(self._conflict_snapshot(session, row) for row in rows)

    def dismiss_conflict(self, command: DismissMemoryConflictCommand) -> MemoryConflict:
        """Dismiss an unresolved conflict under its observed-revision guard.

        Args:
            command:
                Guarded dismissal request.

        Returns:
            Dismissed conflict snapshot.

        Raises:
            MemoryConflictNotFoundError:
                If the conflict is absent or foreign.
            StaleMemoryConflictError:
                If its observed target is no longer current.
            ExtractionEffectConflictError:
                If the conflict was already dismissed.
        """

        with self._factory() as session, session.begin():
            observed = session.scalar(
                select(MemoryConflictModel).where(
                    MemoryConflictModel.id == command.conflict_id,
                    MemoryConflictModel.continuity_id == command.continuity_id,
                )
            )
            if observed is None:
                raise MemoryConflictNotFoundError(str(command.conflict_id))
            if command.expected_revision_id != observed.observed_revision_id:
                raise StaleMemoryConflictError(
                    "Dismissal does not match the conflict's observed revision"
                )

            if observed.memory_id is not None:
                current = session.scalar(
                    select(StorylineMemoryModel.current_revision_id)
                    .where(
                        StorylineMemoryModel.id == observed.memory_id,
                        StorylineMemoryModel.continuity_id == command.continuity_id,
                    )
                    .with_for_update()
                )
                if current != observed.observed_revision_id:
                    raise StaleMemoryConflictError(
                        "Target memory changed after the conflict was recorded"
                    )

            row = session.scalar(
                select(MemoryConflictModel)
                .where(
                    MemoryConflictModel.id == command.conflict_id,
                    MemoryConflictModel.continuity_id == command.continuity_id,
                )
                .with_for_update()
            )
            if row is None:
                raise MemoryConflictNotFoundError(str(command.conflict_id))

            self._conflict_snapshot(session, row).validate_dismissal(command)
            row.state = MemoryConflictState.DISMISSED.value
            row.dismissed_at = datetime.now(UTC)
            session.flush()

            return self._conflict_snapshot(session, row)

    @staticmethod
    def _validate_reservation(
        session: Session,
        scope: ConversationScope,
        scene_id: UUID,
        source_persona_message_id: UUID,
    ) -> None:
        """Validate active Storyline ownership and selected complete-turn ancestry.

        Args:
            session:
                Current transaction.
            scope:
                Complete source ownership.
            scene_id:
                Expected source scene.
            source_persona_message_id:
                Expected selected persona checkpoint.

        Raises:
            ExtractionEffectConflictError:
                If any durable source fact is ineligible.
        """

        conversation = session.scalar(
            select(ConversationModel)
            .where(
                ConversationModel.id == scope.conversation_id,
                ConversationModel.continuity_id == scope.continuity_id,
                ConversationModel.identity_id == scope.identity_id,
                ConversationModel.persona_id == scope.persona_id,
                ConversationModel.mode == "storyline",
            )
            .with_for_update()
        )
        continuity = session.scalar(
            select(ContinuityModel).where(
                ContinuityModel.id == scope.continuity_id,
                ContinuityModel.identity_id == scope.identity_id,
                ContinuityModel.persona_id == scope.persona_id,
                ContinuityModel.mode == "storyline",
                ContinuityModel.lifecycle == "active",
            )
        )
        scene = session.scalar(
            select(SceneModel).where(
                SceneModel.id == scene_id,
                SceneModel.continuity_id == scope.continuity_id,
                SceneModel.identity_id == scope.identity_id,
                SceneModel.persona_id == scope.persona_id,
                SceneModel.conversation_id == scope.conversation_id,
            )
        )
        source = session.scalar(
            select(MessageModel).where(
                MessageModel.id == source_persona_message_id,
                MessageModel.conversation_id == scope.conversation_id,
                MessageModel.continuity_id == scope.continuity_id,
                MessageModel.role == "persona",
            )
        )
        if (
            conversation is None
            or continuity is None
            or scene is None
            or source is None
            or source.parent_id is None
            or conversation.selected_leaf_id is None
        ):
            raise ExtractionEffectConflictError(
                "Source is not an active complete Storyline turn"
            )

        parent = session.scalar(
            select(MessageModel).where(
                MessageModel.id == source.parent_id,
                MessageModel.conversation_id == scope.conversation_id,
                MessageModel.continuity_id == scope.continuity_id,
                MessageModel.role == "user",
            )
        )
        selected = conversation.selected_leaf_id
        while selected is not None and selected != source.id:
            selected = session.scalar(
                select(MessageModel.parent_id).where(
                    MessageModel.id == selected,
                    MessageModel.conversation_id == scope.conversation_id,
                    MessageModel.continuity_id == scope.continuity_id,
                )
            )

        if parent is None or selected != source.id:
            raise ExtractionEffectConflictError(
                "Source persona message is not on the selected complete path"
            )

    @staticmethod
    def _effect_row(
        session: Session,
        scope: ConversationScope,
        source_persona_message_id: UUID,
    ) -> MemoryExtractionEffectModel | None:
        """Return an effect only under complete ownership.

        Args:
            session:
                Current database session.
            scope:
                Expected complete ownership.
            source_persona_message_id:
                Source persona checkpoint.

        Returns:
            Matching persistence row or None.
        """

        return session.scalar(
            select(MemoryExtractionEffectModel).where(
                MemoryExtractionEffectModel.source_persona_message_id
                == source_persona_message_id,
                MemoryExtractionEffectModel.conversation_id == scope.conversation_id,
                MemoryExtractionEffectModel.continuity_id == scope.continuity_id,
                MemoryExtractionEffectModel.identity_id == scope.identity_id,
                MemoryExtractionEffectModel.persona_id == scope.persona_id,
            )
        )

    def _create(
        self,
        session: Session,
        effect: MemoryExtractionEffectModel,
        command: CreateMemoryCommand,
    ) -> None:
        """Persist one create command.

        Args:
            session:
                Current transaction.
            effect:
                Reserved owning effect.
            command:
                Validated create command.
        """

        memory_id = uuid4()
        revision_id = uuid4()
        memory = StorylineMemoryModel(
            id=memory_id,
            continuity_id=effect.continuity_id,
            identity_id=effect.identity_id,
            persona_id=effect.persona_id,
            current_revision_id=None,
            subject_key=command.subject.casefold(),
        )
        session.add(memory)
        session.flush()

        evidence = self._add_evidence(
            session, effect, command.evidence, memory_id, "support"
        )
        session.add(
            MemoryRevisionModel(
                id=revision_id,
                memory_id=memory_id,
                continuity_id=effect.continuity_id,
                revision=1,
                predecessor_id=None,
                subject=command.subject,
                content=command.content,
                state=MemoryRevisionState.ACTIVE.value,
                authorship=MemoryAuthorship.EXTRACTED.value,
                kind=MemoryRevisionKind.EXTRACTION.value,
                source_evidence_id=evidence.id,
                created_at=datetime.now(UTC),
            )
        )
        session.flush()
        memory.current_revision_id = revision_id

    def _reinforce(
        self,
        session: Session,
        effect: MemoryExtractionEffectModel,
        command: ReinforceMemoryCommand,
    ) -> None:
        """Attach unique evidence to unchanged active memory.

        Args:
            session:
                Current transaction.
            effect:
                Reserved owning effect.
            command:
                Validated reinforcement command.
        """

        memory, current = self._target(session, effect, command)
        if current.content != command.content:
            raise InvalidMemoryDeltaTargetError("Reinforcement content changed")

        self._add_evidence(session, effect, command.evidence, memory.id, "support")

    def _supersede(
        self,
        session: Session,
        effect: MemoryExtractionEffectModel,
        command: SupersedeMemoryCommand,
    ) -> None:
        """Add one consecutive automatic replacement revision.

        Args:
            session:
                Current transaction.
            effect:
                Reserved owning effect.
            command:
                Validated supersede command.

        Raises:
            ProtectedMemoryCorrectionError:
                If current content is user-authored.
        """

        memory, current = self._target(session, effect, command)
        if current.authorship != MemoryAuthorship.EXTRACTED:
            raise ProtectedMemoryCorrectionError(
                "Automatic extraction cannot supersede user content"
            )

        evidence = self._add_evidence(
            session, effect, command.evidence, memory.id, "support"
        )
        current.state = MemoryRevisionState.SUPERSEDED.value
        revision_id = uuid4()
        session.add(
            MemoryRevisionModel(
                id=revision_id,
                memory_id=memory.id,
                continuity_id=memory.continuity_id,
                revision=current.revision + 1,
                predecessor_id=current.id,
                subject=command.subject,
                content=command.content,
                state=MemoryRevisionState.ACTIVE.value,
                authorship=MemoryAuthorship.EXTRACTED.value,
                kind=MemoryRevisionKind.AUTOMATIC_SUPERSEDE.value,
                source_evidence_id=evidence.id,
                created_at=datetime.now(UTC),
            )
        )
        session.flush()

        memory.current_revision_id = revision_id
        memory.subject_key = command.subject.casefold()

    def _conflict(
        self,
        session: Session,
        effect: MemoryExtractionEffectModel,
        command: RecordMemoryConflictCommand,
    ) -> None:
        """Record a conflict without changing current memory.

        Args:
            session:
                Current transaction.
            effect:
                Reserved owning effect.
            command:
                Validated conflict command.
        """

        memory_id = command.target_memory_id
        if memory_id is not None:
            self._target(session, effect, command)
        evidence = self._add_evidence(
            session, effect, command.evidence, memory_id, "conflict"
        )
        now = datetime.now(UTC)
        session.add(
            MemoryConflictModel(
                continuity_id=effect.continuity_id,
                identity_id=effect.identity_id,
                persona_id=effect.persona_id,
                memory_id=memory_id,
                observed_revision_id=command.expected_revision_id,
                evidence_id=evidence.id,
                effect_id=effect.id,
                proposed_subject=command.subject,
                proposed_content=command.content,
                state=MemoryConflictState.UNRESOLVED.value,
                created_at=now,
            )
        )

    @staticmethod
    def _target(
        session: Session,
        effect: MemoryExtractionEffectModel,
        command: (
            ReinforceMemoryCommand
            | SupersedeMemoryCommand
            | RecordMemoryConflictCommand
        ),
    ) -> tuple[StorylineMemoryModel, MemoryRevisionModel]:
        """Lock and validate an active current extraction target.

        Args:
            session:
                Current transaction.
            effect:
                Reserved owning effect.
            command:
                Command carrying target and expected revision identifiers.

        Returns:
            Locked logical memory and current revision.

        Raises:
            InvalidMemoryDeltaTargetError:
                If ownership, current revision, or state changed.
        """

        memory = session.scalar(
            select(StorylineMemoryModel)
            .where(
                StorylineMemoryModel.id == command.target_memory_id,
                StorylineMemoryModel.continuity_id == effect.continuity_id,
                StorylineMemoryModel.identity_id == effect.identity_id,
                StorylineMemoryModel.persona_id == effect.persona_id,
            )
            .with_for_update()
        )
        if memory is None or memory.current_revision_id != command.expected_revision_id:
            raise InvalidMemoryDeltaTargetError(
                "Memory target is foreign, missing, or stale"
            )

        current = session.get(MemoryRevisionModel, memory.current_revision_id)
        if current is None or current.state != MemoryRevisionState.ACTIVE:
            raise InvalidMemoryDeltaTargetError("Memory target is not active")

        return memory, current

    @staticmethod
    def _add_evidence(
        session: Session,
        effect: MemoryExtractionEffectModel,
        evidence: MemoryEvidence,
        memory_id: UUID | None,
        purpose: str,
    ) -> MemoryEvidenceModel:
        """Validate and persist immutable source evidence.

        Args:
            session:
                Current transaction.
            effect:
                Reserved source effect.
            evidence:
                Exact evidence supplied by the validated delta.
            memory_id:
                Supported logical memory, when any.
            purpose:
                Supporting or conflict evidence classification.

        Returns:
            New evidence persistence row.

        Raises:
            InvalidTemporalProvenanceError:
                If durable source facts do not match the evidence.
        """

        if (
            evidence.scope != _scope(effect)
            or evidence.scene_id != effect.scene_id
            or evidence.persona_message_id != effect.source_persona_message_id
            or evidence.learned.scene_id != effect.scene_id
        ):
            raise InvalidTemporalProvenanceError(
                "Evidence does not match the reserved source"
            )

        scene = session.get(SceneModel, effect.scene_id)
        persona = session.get(MessageModel, effect.source_persona_message_id)
        user = session.get(MessageModel, evidence.user_message_id)
        occurrence = session.get(SceneModel, evidence.occurrence.scene_id)
        if (
            scene is None
            or persona is None
            or user is None
            or occurrence is None
            or persona.role != "persona"
            or user.role != "user"
            or persona.parent_id != user.id
            or _message_position(session, persona) != evidence.persona_checkpoint
            or scene.position != evidence.learned.position
            or occurrence.continuity_id != effect.continuity_id
            or occurrence.position != evidence.occurrence.position
        ):
            raise InvalidTemporalProvenanceError(
                "Evidence message or temporal provenance is inconsistent"
            )

        row = MemoryEvidenceModel(
            id=evidence.id,
            memory_id=memory_id,
            continuity_id=effect.continuity_id,
            identity_id=effect.identity_id,
            persona_id=effect.persona_id,
            conversation_id=effect.conversation_id,
            mode="storyline",
            purpose=purpose,
            scene_id=effect.scene_id,
            user_message_id=evidence.user_message_id,
            source_persona_message_id=evidence.persona_message_id,
            persona_checkpoint=evidence.persona_checkpoint,
            occurrence_scene_id=evidence.occurrence.scene_id,
            occurrence_position=evidence.occurrence.position,
            learned_scene_id=evidence.learned.scene_id,
            learned_position=evidence.learned.position,
            extraction=evidence.extraction.model_dump(mode="json"),
            created_at=evidence.created_at,
        )
        session.add(row)
        session.flush()

        return row

    @staticmethod
    def _evidence_snapshot(row: MemoryEvidenceModel) -> MemoryEvidence:
        """Convert one evidence row to its immutable domain value.

        Args:
            row:
                Evidence persistence row.

        Returns:
            Detached evidence snapshot.
        """

        return MemoryEvidence(
            id=row.id,
            scope=ConversationScope(
                identity_id=row.identity_id,
                persona_id=row.persona_id,
                continuity_id=row.continuity_id,
                conversation_id=row.conversation_id,
            ),
            scene_id=row.scene_id,
            user_message_id=row.user_message_id,
            persona_message_id=row.source_persona_message_id,
            persona_checkpoint=row.persona_checkpoint,
            occurrence=ScenePosition(
                scene_id=row.occurrence_scene_id, position=row.occurrence_position
            ),
            learned=ScenePosition(
                scene_id=row.learned_scene_id, position=row.learned_position
            ),
            extraction=ExtractionProvenance.model_validate(row.extraction),
            created_at=_aware(row.created_at),
        )

    @staticmethod
    def _effect_snapshot(row: MemoryExtractionEffectModel) -> ExtractionEffect:
        """Convert one effect row to its immutable domain value.

        Args:
            row:
                Effect persistence row.

        Returns:
            Detached extraction effect.
        """

        return ExtractionEffect(
            id=row.id,
            scope=_scope(row),
            scene_id=row.scene_id,
            source_persona_message_id=row.source_persona_message_id,
            state=ExtractionEffectState(row.state),
            provenance=(
                None
                if row.provenance is None
                else ExtractionProvenance.model_validate(row.provenance)
            ),
            created_at=_aware(row.created_at),
            completed_at=(
                None if row.completed_at is None else _aware(row.completed_at)
            ),
        )

    @classmethod
    def _conflict_snapshot(
        cls, session: Session, row: MemoryConflictModel
    ) -> MemoryConflict:
        """Convert one conflict and its evidence to a domain value.

        Args:
            session:
                Current database session.
            row:
                Conflict persistence row.

        Returns:
            Detached conflict snapshot.
        """

        evidence = session.get(MemoryEvidenceModel, row.evidence_id)
        if evidence is None:
            raise MemoryConflictNotFoundError(str(row.id))
        return MemoryConflict(
            id=row.id,
            continuity_id=row.continuity_id,
            memory_id=row.memory_id,
            observed_revision_id=row.observed_revision_id,
            proposed_subject=row.proposed_subject,
            proposed_content=row.proposed_content,
            evidence=cls._evidence_snapshot(evidence),
            state=MemoryConflictState(row.state),
            created_at=_aware(row.created_at),
            dismissed_at=(
                None if row.dismissed_at is None else _aware(row.dismissed_at)
            ),
        )


def _scope(row: MemoryExtractionEffectModel) -> ConversationScope:
    """Build complete ownership from an extraction-effect row.

    Args:
        row:
            Extraction-effect persistence row.

    Returns:
        Complete conversation scope.
    """

    return ConversationScope(
        identity_id=row.identity_id,
        persona_id=row.persona_id,
        continuity_id=row.continuity_id,
        conversation_id=row.conversation_id,
    )


def _aware(value: datetime) -> datetime:
    """Restore UTC awareness when SQLite returns a naive timestamp.

    Args:
        value:
            Persisted timestamp.

    Returns:
        UTC-aware timestamp.
    """

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _required_current(row: StorylineMemoryModel) -> UUID:
    """Return the current revision of a logical memory.

    Args:
        row:
            Logical-memory persistence row.

    Returns:
        Required current revision identifier.

    Raises:
        MemoryNotFoundError:
            If persistence contains an incomplete lineage.
    """

    if row.current_revision_id is None:
        raise MemoryNotFoundError(f"Memory {row.id} has no current revision")
    return row.current_revision_id


def _message_position(session: Session, message: MessageModel) -> int:
    """Return one message's one-based position on its parent ancestry.

    Args:
        session:
            Current database session.
        message:
            Final source message.

    Returns:
        One-based ancestry position.

    Raises:
        InvalidTemporalProvenanceError:
            If persistence contains a broken or cyclic source ancestry.
    """

    position = 0
    current: MessageModel | None = message
    visited: set[UUID] = set()
    while current is not None:
        if current.id in visited:
            raise InvalidTemporalProvenanceError("Source ancestry contains a cycle")
        visited.add(current.id)
        position += 1
        if current.parent_id is None:
            break
        current = session.get(MessageModel, current.parent_id)
        if current is None:
            raise InvalidTemporalProvenanceError("Source ancestry is incomplete")
    return position
