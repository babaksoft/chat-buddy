"""Transactional evolution effects, events, and projection caches."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    EvolutionCommand,
    EvolutionCorrectionAction,
    EvolutionCorrectionConflictError,
    EvolutionCorrectionEvent,
    EvolutionDecision,
    EvolutionDecisionOutcome,
    EvolutionEffect,
    EvolutionEffectConflictError,
    EvolutionEffectState,
    EvolutionEvent,
    EvolutionEvidenceKind,
    EvolutionEvidenceReference,
    EvolutionProjectionConflictError,
    EvolutionProjectionState,
    EvolutionProposal,
    EvolutionProvenance,
    EvolutionScope,
    PersonaAdaptationProjection,
    RelationshipProjection,
    RemovePersonaAdaptationCommand,
    SetPersonaAdaptationCommand,
)
from chat_buddy.characters.infrastructure.db.models import (
    ConversationModel,
    EvolutionCorrectionEventModel,
    EvolutionEffectModel,
    EvolutionEventModel,
    MessageModel,
    PersonaAdaptationProjectionModel,
    RelationshipProjectionModel,
    SceneModel,
)

_EVOLUTION_COMMAND_ADAPTER: TypeAdapter[EvolutionCommand] = TypeAdapter(
    EvolutionCommand
)


class DbEvolutionRepository:
    """Persist evolution history and atomically maintain rebuildable caches."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory:
                Factory used for short database transactions.
        """

        self._factory = session_factory

    def initialize(
        self,
        relationship: RelationshipProjection,
        persona_adaptations: PersonaAdaptationProjection,
    ) -> EvolutionProjectionState:
        """Create paired revision-zero caches, or return identical existing caches.

        Args:
            relationship:
                Starting relationship projection.
            persona_adaptations:
                Starting empty adaptation projection.

        Returns:
            Persisted paired cache state.

        Raises:
            EvolutionProjectionConflictError:
                If owners, revisions, or existing cache contents conflict.
        """

        if relationship.scope != persona_adaptations.scope:
            raise EvolutionProjectionConflictError(
                "Evolution projection owners must match"
            )
        if relationship.revision != 0 or persona_adaptations.revision != 0:
            raise EvolutionProjectionConflictError(
                "Evolution projections must initialize at revision zero"
            )

        now = datetime.now(UTC)
        scope = relationship.scope
        try:
            with self._factory() as session, session.begin():
                existing = self._projection_rows(session, scope)
                if existing is not None:
                    state = self._projection_snapshot(*existing)
                    if (
                        state.relationship != relationship
                        or state.persona_adaptations != persona_adaptations
                    ):
                        raise EvolutionProjectionConflictError(
                            "Evolution projections were initialized differently"
                        )
                    return state

                session.add_all(
                    [
                        RelationshipProjectionModel(
                            continuity_id=scope.continuity_id,
                            identity_id=scope.identity_id,
                            persona_id=scope.persona_id,
                            revision=0,
                            rebuild_checkpoint_id=None,
                            snapshot=relationship.model_dump(mode="json"),
                            updated_at=now,
                        ),
                        PersonaAdaptationProjectionModel(
                            continuity_id=scope.continuity_id,
                            identity_id=scope.identity_id,
                            persona_id=scope.persona_id,
                            revision=0,
                            rebuild_checkpoint_id=None,
                            snapshot=persona_adaptations.model_dump(mode="json"),
                            updated_at=now,
                        ),
                    ]
                )
                session.flush()

                rows = self._projection_rows(session, scope)
                assert rows is not None

                return self._projection_snapshot(*rows)
        except IntegrityError as error:
            try:
                existing_state = self.get_projections(scope)
            except EvolutionProjectionConflictError:
                raise EvolutionProjectionConflictError(
                    "Evolution projection initialization violated ownership"
                ) from error
            if (
                existing_state.relationship == relationship
                and existing_state.persona_adaptations == persona_adaptations
            ):
                return existing_state

            raise EvolutionProjectionConflictError(
                "Evolution projections changed during initialization"
            ) from error

    def get_projections(self, scope: EvolutionScope) -> EvolutionProjectionState:
        """Read both current caches under complete ownership.

        Args:
            scope:
                Required evolution ownership.

        Returns:
            Detached paired projection state.

        Raises:
            EvolutionProjectionConflictError:
                If either paired cache is missing or foreign.
        """

        with self._factory() as session:
            rows = self._projection_rows(session, scope)
            if rows is None:
                raise EvolutionProjectionConflictError(
                    "Evolution projection caches are not initialized"
                )

            return self._projection_snapshot(*rows)

    def reserve(
        self, source: EvolutionEvidenceReference, provenance: EvolutionProvenance
    ) -> EvolutionEffect:
        """Reserve or resume the unique effect for a persona checkpoint.

        Args:
            source:
                Exact selected persona checkpoint.
            provenance:
                Configuration fixed for the effect.

        Returns:
            Existing identical effect or a new reservation.

        Raises:
            EvolutionEffectConflictError:
                If evidence is not an owned completed turn or audit data conflicts.
        """

        now = datetime.now(UTC)
        try:
            with self._factory() as session, session.begin():
                existing = self._effect_by_source(
                    session, source.scope, source.persona_message_id
                )
                if existing is not None:
                    return self._resume(existing, source, provenance)

                self._validate_source(session, source)
                row = EvolutionEffectModel(
                    id=uuid4(),
                    continuity_id=source.scope.continuity_id,
                    identity_id=source.scope.identity_id,
                    persona_id=source.scope.persona_id,
                    conversation_id=source.conversation_id,
                    source_persona_message_id=source.persona_message_id,
                    source=source.model_dump(mode="json"),
                    state=EvolutionEffectState.RESERVED.value,
                    provenance=provenance.model_dump(mode="json"),
                    proposal=None,
                    decision=None,
                    created_at=now,
                    completed_at=None,
                )
                session.add(row)
                session.flush()

                return self._effect_snapshot(row)
        except IntegrityError as error:
            with self._factory() as session:
                existing = self._effect_by_source(
                    session, source.scope, source.persona_message_id
                )
                if existing is not None:
                    return self._resume(existing, source, provenance)

            raise EvolutionEffectConflictError(
                "Evolution effect reservation violated checkpoint ownership"
            ) from error

    def get_effect(
        self, scope: EvolutionScope, source_persona_message_id: UUID
    ) -> EvolutionEffect:
        """Read one effect under complete ownership.

        Args:
            scope:
                Required evolution ownership.
            source_persona_message_id:
                Unique source checkpoint identifier.

        Returns:
            Detached effect audit record.

        Raises:
            EvolutionEffectConflictError:
                If no owned effect exists.
        """

        with self._factory() as session:
            row = self._effect_by_source(session, scope, source_persona_message_id)
            if row is None:
                raise EvolutionEffectConflictError("Evolution effect does not exist")

            return self._effect_snapshot(row)

    def list_effects(self, scope: EvolutionScope) -> tuple[EvolutionEffect, ...]:
        """Read all effect audit records in deterministic source order.

        Args:
            scope:
                Required evolution ownership.

        Returns:
            Immutable effect snapshots, including rejected proposals.
        """

        with self._factory() as session:
            rows = session.scalars(
                select(EvolutionEffectModel)
                .where(
                    EvolutionEffectModel.continuity_id == scope.continuity_id,
                    EvolutionEffectModel.identity_id == scope.identity_id,
                    EvolutionEffectModel.persona_id == scope.persona_id,
                )
                .order_by(
                    EvolutionEffectModel.created_at,
                    EvolutionEffectModel.id,
                )
            )

            return tuple(self._effect_snapshot(row) for row in rows)

    def complete(
        self,
        effect_id: UUID,
        proposal: EvolutionProposal,
        decision: EvolutionDecision,
        relationship: RelationshipProjection | None = None,
        persona_adaptations: PersonaAdaptationProjection | None = None,
    ) -> EvolutionEffect:
        """Atomically commit a terminal decision, events, and updated caches.

        Args:
            effect_id:
                Reserved effect identifier.
            proposal:
                Exact bounded proposal audit data.
            decision:
                Terminal validation result.
            relationship:
                Updated relationship cache for an applied decision.
            persona_adaptations:
                Updated adaptation cache for an applied decision.

        Returns:
            Terminal detached effect.

        Raises:
            EvolutionEffectConflictError:
                If the reservation or terminal audit data conflicts.
            EvolutionProjectionConflictError:
                If an applied decision conflicts with current caches.
        """

        now = datetime.now(UTC)
        try:
            with self._factory() as session, session.begin():
                row = session.scalar(
                    select(EvolutionEffectModel)
                    .where(EvolutionEffectModel.id == effect_id)
                    .with_for_update()
                )
                if row is None:
                    raise EvolutionEffectConflictError(
                        "Evolution effect does not exist"
                    )

                if row.state != EvolutionEffectState.RESERVED.value:
                    existing = self._effect_snapshot(row)
                    if existing.proposal == proposal and existing.decision == decision:
                        return existing

                    raise EvolutionEffectConflictError(
                        "Evolution effect is already terminal"
                    )

                self._validate_terminal(row, proposal, decision)
                if decision.outcome == EvolutionDecisionOutcome.APPLIED:
                    if relationship is None or persona_adaptations is None:
                        raise EvolutionProjectionConflictError(
                            "Applied evolution requires both updated projections"
                        )

                    self._apply(
                        session,
                        row,
                        proposal,
                        decision,
                        relationship,
                        persona_adaptations,
                        now,
                    )
                elif relationship is not None or persona_adaptations is not None:
                    raise EvolutionProjectionConflictError(
                        "Non-applied evolution cannot replace projections"
                    )

                row.state = decision.outcome.value
                row.proposal = proposal.model_dump(mode="json")
                row.decision = decision.model_dump(mode="json")
                row.completed_at = now
                session.flush()

                return self._effect_snapshot(row)
        except IntegrityError as error:
            raise EvolutionProjectionConflictError(
                "Evolution changed concurrently while committing"
            ) from error

    def list_events(self, scope: EvolutionScope) -> tuple[EvolutionEvent, ...]:
        """Read authoritative accepted events in append order.

        Args:
            scope:
                Required evolution ownership.

        Returns:
            Immutable accepted event snapshots.
        """

        with self._factory() as session:
            rows = session.scalars(
                select(EvolutionEventModel)
                .where(
                    EvolutionEventModel.continuity_id == scope.continuity_id,
                    EvolutionEventModel.identity_id == scope.identity_id,
                    EvolutionEventModel.persona_id == scope.persona_id,
                )
                .order_by(
                    EvolutionEventModel.relationship_revision
                    + EvolutionEventModel.adaptation_revision,
                    EvolutionEventModel.relationship_revision,
                    EvolutionEventModel.adaptation_revision,
                    EvolutionEventModel.id,
                )
            )

            return tuple(self._event_snapshot(row) for row in rows)

    def list_corrections(
        self, scope: EvolutionScope
    ) -> tuple[EvolutionCorrectionEvent, ...]:
        """Read append-only user corrections in replay order.

        Args:
            scope:
                Required evolution ownership.

        Returns:
            Immutable user correction snapshots.
        """

        with self._factory() as session:
            rows = session.scalars(
                select(EvolutionCorrectionEventModel)
                .where(
                    EvolutionCorrectionEventModel.continuity_id == scope.continuity_id,
                    EvolutionCorrectionEventModel.identity_id == scope.identity_id,
                    EvolutionCorrectionEventModel.persona_id == scope.persona_id,
                )
                .order_by(
                    EvolutionCorrectionEventModel.relationship_revision
                    + EvolutionCorrectionEventModel.adaptation_revision,
                    EvolutionCorrectionEventModel.relationship_revision,
                    EvolutionCorrectionEventModel.adaptation_revision,
                    EvolutionCorrectionEventModel.id,
                )
            )

            return tuple(self._correction_snapshot(row) for row in rows)

    def append_correction(
        self,
        correction: EvolutionCorrectionEvent,
        relationship: RelationshipProjection,
        persona_adaptations: PersonaAdaptationProjection,
    ) -> EvolutionProjectionState:
        """Append one guarded correction and commit replayed caches atomically.

        Args:
            correction:
                User-authored correction event.
            relationship:
                Fully replayed relationship projection.
            persona_adaptations:
                Fully replayed adaptation projection.

        Returns:
            Persisted paired cache state.

        Raises:
            EvolutionCorrectionConflictError:
                If ownership, target, or observed revisions conflict.
        """

        now = datetime.now(UTC)
        try:
            with self._factory() as session, session.begin():
                rows = self._projection_rows(session, correction.scope, lock=True)
                if rows is None:
                    raise EvolutionCorrectionConflictError(
                        "Evolution projection caches are not initialized"
                    )

                relationship_row, adaptation_row = rows
                if (
                    relationship_row.revision
                    != correction.expected_relationship_revision
                    or adaptation_row.revision
                    != correction.expected_adaptation_revision
                ):
                    raise EvolutionCorrectionConflictError(
                        "Evolution correction used stale projection revisions"
                    )

                target = session.scalar(
                    select(EvolutionEventModel).where(
                        EvolutionEventModel.id == correction.target_event_id,
                        EvolutionEventModel.continuity_id
                        == correction.scope.continuity_id,
                        EvolutionEventModel.identity_id == correction.scope.identity_id,
                        EvolutionEventModel.persona_id == correction.scope.persona_id,
                    )
                )
                if target is None:
                    raise EvolutionCorrectionConflictError(
                        "Evolution correction target does not exist"
                    )

                target_event = self._event_snapshot(target)
                adaptation_target = isinstance(
                    target_event.command,
                    (SetPersonaAdaptationCommand, RemovePersonaAdaptationCommand),
                )
                if (
                    correction.relationship_revision
                    != correction.expected_relationship_revision
                    + (not adaptation_target)
                    or correction.adaptation_revision
                    != correction.expected_adaptation_revision + adaptation_target
                ):
                    raise EvolutionCorrectionConflictError(
                        "Evolution correction revisions are not contiguous"
                    )

                if correction.replacement is not None and (
                    isinstance(
                        correction.replacement,
                        (
                            SetPersonaAdaptationCommand,
                            RemovePersonaAdaptationCommand,
                        ),
                    )
                    != adaptation_target
                ):
                    raise EvolutionCorrectionConflictError(
                        "Evolution replacement changed projection type"
                    )

                if correction.replacement is not None:
                    changed_target = (
                        correction.replacement.kind != target_event.command.kind
                        or correction.replacement.sources
                        != target_event.command.sources
                    )
                    if isinstance(
                        correction.replacement,
                        (
                            SetPersonaAdaptationCommand,
                            RemovePersonaAdaptationCommand,
                        ),
                    ) and isinstance(
                        target_event.command,
                        (
                            SetPersonaAdaptationCommand,
                            RemovePersonaAdaptationCommand,
                        ),
                    ):
                        changed_target = (
                            changed_target
                            or correction.replacement.facet
                            != target_event.command.facet
                        )
                    if changed_target:
                        raise EvolutionCorrectionConflictError(
                            "Evolution replacement changed its inferred target"
                        )

                if correction.action == EvolutionCorrectionAction.RESTORE:
                    prior = session.scalar(
                        select(EvolutionCorrectionEventModel)
                        .where(
                            EvolutionCorrectionEventModel.continuity_id
                            == correction.scope.continuity_id,
                            EvolutionCorrectionEventModel.target_event_id
                            == correction.target_event_id,
                        )
                        .order_by(
                            (
                                EvolutionCorrectionEventModel.relationship_revision
                                + EvolutionCorrectionEventModel.adaptation_revision
                            ).desc()
                        )
                        .limit(1)
                    )
                    if (
                        prior is None
                        or prior.action == EvolutionCorrectionAction.RESTORE
                    ):
                        raise EvolutionCorrectionConflictError(
                            "Only a corrected interpretation can be restored"
                        )

                if (
                    relationship.scope != correction.scope
                    or persona_adaptations.scope != correction.scope
                    or relationship.revision != correction.relationship_revision
                    or persona_adaptations.revision != correction.adaptation_revision
                ):
                    raise EvolutionCorrectionConflictError(
                        "Replayed correction projections are inconsistent"
                    )

                session.add(
                    EvolutionCorrectionEventModel(
                        id=correction.id,
                        continuity_id=correction.scope.continuity_id,
                        identity_id=correction.scope.identity_id,
                        persona_id=correction.scope.persona_id,
                        target_event_id=correction.target_event_id,
                        action=correction.action.value,
                        replacement=(
                            correction.replacement.model_dump(mode="json")
                            if correction.replacement is not None
                            else None
                        ),
                        note=correction.note,
                        expected_relationship_revision=correction.expected_relationship_revision,
                        expected_adaptation_revision=correction.expected_adaptation_revision,
                        relationship_revision=correction.relationship_revision,
                        adaptation_revision=correction.adaptation_revision,
                        created_at=correction.created_at,
                    )
                )
                self._replace_projection_rows(
                    relationship_row,
                    adaptation_row,
                    relationship,
                    persona_adaptations,
                    relationship_row.rebuild_checkpoint_id,
                    adaptation_row.rebuild_checkpoint_id,
                    now,
                )
                session.flush()

                return self._projection_snapshot(relationship_row, adaptation_row)
        except IntegrityError as error:
            raise EvolutionCorrectionConflictError(
                "Evolution correction changed concurrently"
            ) from error

    def rebuild_projections(
        self,
        relationship: RelationshipProjection,
        persona_adaptations: PersonaAdaptationProjection,
        relationship_checkpoint_id: UUID | None,
        adaptation_checkpoint_id: UUID | None,
        expected_relationship_revision: int | None = None,
        expected_adaptation_revision: int | None = None,
    ) -> EvolutionProjectionState:
        """Replace or recreate disposable projections from authoritative history.

        Args:
            relationship:
                Fully replayed relationship projection.
            persona_adaptations:
                Fully replayed adaptation projection.
            relationship_checkpoint_id:
                Last inferred relationship event represented.
            adaptation_checkpoint_id:
                Last inferred adaptation event represented.
            expected_relationship_revision:
                Optional observed relationship revision.
            expected_adaptation_revision:
                Optional observed adaptation revision.

        Returns:
            Persisted paired projection state.

        Raises:
            EvolutionProjectionConflictError:
                If ownership or an optimistic revision guard conflicts.
        """

        if relationship.scope != persona_adaptations.scope:
            raise EvolutionProjectionConflictError(
                "Evolution projection owners must match"
            )
        if (expected_relationship_revision is None) != (
            expected_adaptation_revision is None
        ):
            raise EvolutionProjectionConflictError(
                "Evolution rebuild requires both observed revisions"
            )

        now = datetime.now(UTC)
        scope = relationship.scope
        try:
            with self._factory() as session, session.begin():
                rows = self._projection_rows(session, scope, lock=True)
                if rows is None:
                    if (
                        expected_relationship_revision is not None
                        or expected_adaptation_revision is not None
                    ):
                        raise EvolutionProjectionConflictError(
                            "Evolution projection caches were deleted concurrently"
                        )

                    relationship_row = RelationshipProjectionModel(
                        continuity_id=scope.continuity_id,
                        identity_id=scope.identity_id,
                        persona_id=scope.persona_id,
                        revision=relationship.revision,
                        rebuild_checkpoint_id=relationship_checkpoint_id,
                        snapshot=relationship.model_dump(mode="json"),
                        updated_at=now,
                    )
                    adaptation_row = PersonaAdaptationProjectionModel(
                        continuity_id=scope.continuity_id,
                        identity_id=scope.identity_id,
                        persona_id=scope.persona_id,
                        revision=persona_adaptations.revision,
                        rebuild_checkpoint_id=adaptation_checkpoint_id,
                        snapshot=persona_adaptations.model_dump(mode="json"),
                        updated_at=now,
                    )
                    session.add_all([relationship_row, adaptation_row])
                else:
                    relationship_row, adaptation_row = rows
                    if (
                        expected_relationship_revision is not None
                        and relationship_row.revision != expected_relationship_revision
                    ) or (
                        expected_adaptation_revision is not None
                        and adaptation_row.revision != expected_adaptation_revision
                    ):
                        raise EvolutionProjectionConflictError(
                            "Evolution projections changed before rebuild"
                        )

                    self._replace_projection_rows(
                        relationship_row,
                        adaptation_row,
                        relationship,
                        persona_adaptations,
                        relationship_checkpoint_id,
                        adaptation_checkpoint_id,
                        now,
                    )
                session.flush()

                return self._projection_snapshot(relationship_row, adaptation_row)
        except IntegrityError as error:
            raise EvolutionProjectionConflictError(
                "Evolution projections changed concurrently while rebuilding"
            ) from error

    def _apply(
        self,
        session: Session,
        effect: EvolutionEffectModel,
        proposal: EvolutionProposal,
        decision: EvolutionDecision,
        relationship: RelationshipProjection,
        persona_adaptations: PersonaAdaptationProjection,
        now: datetime,
    ) -> None:
        """Append accepted events and replace caches inside one transaction."""

        rows = self._projection_rows(session, proposal.scope, lock=True)
        if rows is None:
            raise EvolutionProjectionConflictError(
                "Evolution projection caches are not initialized"
            )
        relationship_row, adaptation_row = rows
        if (
            relationship_row.revision != proposal.expected_relationship_revision
            or adaptation_row.revision != proposal.expected_adaptation_revision
        ):
            raise EvolutionProjectionConflictError(
                "Evolution proposal used stale projection revisions"
            )
        if (
            relationship.scope != proposal.scope
            or persona_adaptations.scope != proposal.scope
        ):
            raise EvolutionProjectionConflictError(
                "Updated evolution projections are foreign"
            )

        relationship_revision = relationship_row.revision
        adaptation_revision = adaptation_row.revision
        relationship_checkpoint = relationship_row.rebuild_checkpoint_id
        adaptation_checkpoint = adaptation_row.rebuild_checkpoint_id
        for position, event in enumerate(decision.events, start=1):
            adaptation_command = isinstance(
                event.command,
                (SetPersonaAdaptationCommand, RemovePersonaAdaptationCommand),
            )
            expected_relationship = relationship_revision + (not adaptation_command)
            expected_adaptation = adaptation_revision + adaptation_command
            if (
                event.relationship_revision != expected_relationship
                or event.adaptation_revision != expected_adaptation
            ):
                raise EvolutionProjectionConflictError(
                    "Evolution event revisions are not contiguous"
                )
            relationship_revision = event.relationship_revision
            adaptation_revision = event.adaptation_revision
            if adaptation_command:
                adaptation_checkpoint = event.id
            else:
                relationship_checkpoint = event.id
            session.add(
                EvolutionEventModel(
                    id=event.id,
                    effect_id=effect.id,
                    proposal_id=event.proposal_id,
                    continuity_id=event.scope.continuity_id,
                    identity_id=event.scope.identity_id,
                    persona_id=event.scope.persona_id,
                    position=position,
                    command=event.command.model_dump(mode="json"),
                    relationship_revision=event.relationship_revision,
                    adaptation_revision=event.adaptation_revision,
                    provenance=event.provenance.model_dump(mode="json"),
                    created_at=event.created_at,
                )
            )

        if (
            relationship.revision != relationship_revision
            or persona_adaptations.revision != adaptation_revision
        ):
            raise EvolutionProjectionConflictError(
                "Updated projection revisions do not match accepted events"
            )
        relationship_row.revision = relationship.revision
        relationship_row.rebuild_checkpoint_id = relationship_checkpoint
        relationship_row.snapshot = relationship.model_dump(mode="json")
        relationship_row.updated_at = now
        adaptation_row.revision = persona_adaptations.revision
        adaptation_row.rebuild_checkpoint_id = adaptation_checkpoint
        adaptation_row.snapshot = persona_adaptations.model_dump(mode="json")
        adaptation_row.updated_at = now

    @staticmethod
    def _validate_terminal(
        row: EvolutionEffectModel,
        proposal: EvolutionProposal,
        decision: EvolutionDecision,
    ) -> None:
        """Validate terminal audit data against its fixed reservation."""

        source = EvolutionEvidenceReference.model_validate(row.source)
        provenance = EvolutionProvenance.model_validate(row.provenance)
        if proposal.source != source or proposal.provenance != provenance:
            raise EvolutionEffectConflictError(
                "Evolution proposal conflicts with its reservation"
            )
        if decision.proposal_id != proposal.id:
            raise EvolutionEffectConflictError(
                "Evolution decision conflicts with its proposal"
            )
        if decision.outcome == EvolutionDecisionOutcome.NO_CHANGE and proposal.commands:
            raise EvolutionEffectConflictError(
                "No-change decisions require an empty proposal"
            )
        if decision.outcome == EvolutionDecisionOutcome.APPLIED:
            if tuple(event.command for event in decision.events) != proposal.commands:
                raise EvolutionEffectConflictError(
                    "Accepted events do not match the atomic proposal"
                )
            if any(
                event.scope != proposal.scope or event.provenance != proposal.provenance
                for event in decision.events
            ):
                raise EvolutionEffectConflictError(
                    "Accepted event audit data conflicts with the proposal"
                )

    @staticmethod
    def _validate_source(session: Session, source: EvolutionEvidenceReference) -> None:
        """Require an owned adjacent committed user/persona checkpoint."""

        conversation = session.scalar(
            select(ConversationModel).where(
                ConversationModel.id == source.conversation_id,
                ConversationModel.continuity_id == source.scope.continuity_id,
                ConversationModel.identity_id == source.scope.identity_id,
                ConversationModel.persona_id == source.scope.persona_id,
                ConversationModel.mode
                == (
                    "ongoing"
                    if source.kind == EvolutionEvidenceKind.ONGOING_TURN
                    else "storyline"
                ),
            )
        )
        user = session.scalar(
            select(MessageModel).where(
                MessageModel.id == source.user_message_id,
                MessageModel.conversation_id == source.conversation_id,
                MessageModel.continuity_id == source.scope.continuity_id,
                MessageModel.role == "user",
            )
        )
        persona = session.scalar(
            select(MessageModel).where(
                MessageModel.id == source.persona_message_id,
                MessageModel.conversation_id == source.conversation_id,
                MessageModel.continuity_id == source.scope.continuity_id,
                MessageModel.role == "persona",
                MessageModel.parent_id == source.user_message_id,
            )
        )

        scene_is_valid = source.kind == EvolutionEvidenceKind.ONGOING_TURN
        if source.kind == EvolutionEvidenceKind.STORYLINE_CHECKPOINT:
            scene_is_valid = (
                session.scalar(
                    select(SceneModel.id).where(
                        SceneModel.id == source.scene_id,
                        SceneModel.position == source.scene_position,
                        SceneModel.conversation_id == source.conversation_id,
                        SceneModel.continuity_id == source.scope.continuity_id,
                        SceneModel.identity_id == source.scope.identity_id,
                        SceneModel.persona_id == source.scope.persona_id,
                    )
                )
                is not None
            )
        if (
            conversation is None
            or user is None
            or persona is None
            or not scene_is_valid
        ):
            raise EvolutionEffectConflictError(
                "Evolution source is not an owned completed turn"
            )

    @staticmethod
    def _resume(
        row: EvolutionEffectModel,
        source: EvolutionEvidenceReference,
        provenance: EvolutionProvenance,
    ) -> EvolutionEffect:
        """Return an identical reservation or terminal effect."""

        effect = DbEvolutionRepository._effect_snapshot(row)
        if effect.source != source or effect.provenance != provenance:
            raise EvolutionEffectConflictError(
                "Evolution checkpoint was reserved with different audit data"
            )

        return effect

    @staticmethod
    def _effect_by_source(
        session: Session, scope: EvolutionScope, source_id: UUID
    ) -> EvolutionEffectModel | None:
        """Find one effect using complete ownership and its source ID."""

        return session.scalar(
            select(EvolutionEffectModel).where(
                EvolutionEffectModel.source_persona_message_id == source_id,
                EvolutionEffectModel.continuity_id == scope.continuity_id,
                EvolutionEffectModel.identity_id == scope.identity_id,
                EvolutionEffectModel.persona_id == scope.persona_id,
            )
        )

    @staticmethod
    def _projection_rows(
        session: Session, scope: EvolutionScope, lock: bool = False
    ) -> tuple[RelationshipProjectionModel, PersonaAdaptationProjectionModel] | None:
        """Read both cache rows, optionally locking them for replacement."""

        relationship_query = select(RelationshipProjectionModel).where(
            RelationshipProjectionModel.continuity_id == scope.continuity_id,
            RelationshipProjectionModel.identity_id == scope.identity_id,
            RelationshipProjectionModel.persona_id == scope.persona_id,
        )
        adaptation_query = select(PersonaAdaptationProjectionModel).where(
            PersonaAdaptationProjectionModel.continuity_id == scope.continuity_id,
            PersonaAdaptationProjectionModel.identity_id == scope.identity_id,
            PersonaAdaptationProjectionModel.persona_id == scope.persona_id,
        )

        relationship = session.scalar(
            relationship_query.with_for_update() if lock else relationship_query
        )
        adaptation = session.scalar(
            adaptation_query.with_for_update() if lock else adaptation_query
        )

        if relationship is None or adaptation is None:
            return None

        return relationship, adaptation

    @staticmethod
    def _projection_snapshot(
        relationship: RelationshipProjectionModel,
        adaptation: PersonaAdaptationProjectionModel,
    ) -> EvolutionProjectionState:
        """Convert paired persistence rows to a detached domain snapshot."""

        return EvolutionProjectionState(
            relationship=RelationshipProjection.model_validate(relationship.snapshot),
            persona_adaptations=PersonaAdaptationProjection.model_validate(
                adaptation.snapshot
            ),
            relationship_checkpoint_id=relationship.rebuild_checkpoint_id,
            adaptation_checkpoint_id=adaptation.rebuild_checkpoint_id,
            updated_at=max(_utc(relationship.updated_at), _utc(adaptation.updated_at)),
        )

    @staticmethod
    def _replace_projection_rows(
        relationship_row: RelationshipProjectionModel,
        adaptation_row: PersonaAdaptationProjectionModel,
        relationship: RelationshipProjection,
        persona_adaptations: PersonaAdaptationProjection,
        relationship_checkpoint_id: UUID | None,
        adaptation_checkpoint_id: UUID | None,
        updated_at: datetime,
    ) -> None:
        """Replace paired cache rows with one fully replayed state."""

        relationship_row.revision = relationship.revision
        relationship_row.rebuild_checkpoint_id = relationship_checkpoint_id
        relationship_row.snapshot = relationship.model_dump(mode="json")
        relationship_row.updated_at = updated_at
        adaptation_row.revision = persona_adaptations.revision
        adaptation_row.rebuild_checkpoint_id = adaptation_checkpoint_id
        adaptation_row.snapshot = persona_adaptations.model_dump(mode="json")
        adaptation_row.updated_at = updated_at

    @staticmethod
    def _effect_snapshot(row: EvolutionEffectModel) -> EvolutionEffect:
        """Convert an effect persistence row to a detached domain snapshot."""

        return EvolutionEffect(
            id=row.id,
            source=EvolutionEvidenceReference.model_validate(row.source),
            state=EvolutionEffectState(row.state),
            provenance=EvolutionProvenance.model_validate(row.provenance),
            proposal=(
                EvolutionProposal.model_validate(row.proposal)
                if row.proposal is not None
                else None
            ),
            decision=(
                EvolutionDecision.model_validate(row.decision)
                if row.decision is not None
                else None
            ),
            created_at=_utc(row.created_at),
            completed_at=(
                _utc(row.completed_at) if row.completed_at is not None else None
            ),
        )

    @staticmethod
    def _event_snapshot(row: EvolutionEventModel) -> EvolutionEvent:
        """Convert an event persistence row to a detached domain snapshot."""

        return EvolutionEvent(
            id=row.id,
            proposal_id=row.proposal_id,
            scope=EvolutionScope(
                identity_id=row.identity_id,
                persona_id=row.persona_id,
                continuity_id=row.continuity_id,
            ),
            command=_EVOLUTION_COMMAND_ADAPTER.validate_python(row.command),
            relationship_revision=row.relationship_revision,
            adaptation_revision=row.adaptation_revision,
            provenance=EvolutionProvenance.model_validate(row.provenance),
            created_at=_utc(row.created_at),
        )

    @staticmethod
    def _correction_snapshot(
        row: EvolutionCorrectionEventModel,
    ) -> EvolutionCorrectionEvent:
        """Convert a user correction row to a detached domain snapshot."""

        return EvolutionCorrectionEvent(
            id=row.id,
            scope=EvolutionScope(
                identity_id=row.identity_id,
                persona_id=row.persona_id,
                continuity_id=row.continuity_id,
            ),
            target_event_id=row.target_event_id,
            action=EvolutionCorrectionAction(row.action),
            replacement=(
                _EVOLUTION_COMMAND_ADAPTER.validate_python(row.replacement)
                if row.replacement is not None
                else None
            ),
            note=row.note,
            expected_relationship_revision=row.expected_relationship_revision,
            expected_adaptation_revision=row.expected_adaptation_revision,
            relationship_revision=row.relationship_revision,
            adaptation_revision=row.adaptation_revision,
            created_at=_utc(row.created_at),
        )


def _utc(value: datetime) -> datetime:
    """Normalize database timestamps, including SQLite's naive values."""

    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
