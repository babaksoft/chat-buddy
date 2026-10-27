"""Post-completion validation and persistence of Storyline memory deltas."""

from __future__ import annotations

from uuid import UUID

from chat_buddy.characters.application.memory_context import (
    StorylineExtractionContextService,
)
from chat_buddy.characters.domain import (
    ContinuityMode,
    ConversationTarget,
    ExtractionBudget,
    ExtractionEffect,
    ExtractionEffectConflictError,
    ExtractionEffectState,
    ExtractionProvenance,
    InvalidMemoryDeltaTargetError,
    MemoryAuthorship,
    MemoryDelta,
    MemoryDeltaExtractor,
    MemoryExtractionRepository,
    MemoryRevisionState,
    MemorySelectionResult,
    MemorySubjectConflictError,
    ProtectedMemoryCorrectionError,
    RecordMemoryConflictCommand,
    ReinforceMemoryCommand,
    StorylineMemory,
    StorylineMemoryRepository,
    SupersedeMemoryCommand,
    UnsupportedContinuityModeError,
)


class StorylineMemoryExtractionService:
    """Turn one eligible completed Storyline response into one atomic effect."""

    def __init__(
        self,
        contexts: StorylineExtractionContextService,
        extractor: MemoryDeltaExtractor,
        memories: StorylineMemoryRepository,
        effects: MemoryExtractionRepository,
        budget: ExtractionBudget,
    ) -> None:
        """Bind read, interpretation, validation, and transactional write seams.

        Args:
            contexts:
                Read-only contextual snapshot builder.
            extractor:
                Provider-backed proposal strategy without write authority.
            memories:
                Current lineage reader used for application-side reconciliation.
            effects:
                Idempotent reservation and atomic delta repository.
            budget:
                Dedicated extraction input budget.
        """

        self._contexts = contexts
        self._extractor = extractor
        self._memories = memories
        self._effects = effects
        self._budget = budget

    def process(
        self, target: ConversationTarget, source_persona_message_id: UUID
    ) -> ExtractionEffect:
        """Extract and atomically apply memory for one completed selected turn.

        A provider or validation failure deliberately leaves the reservation open
        for a later retry. Conversation completion occurs before this workflow and
        is never part of its transaction.

        Args:
            target:
                Exact mode-owned scene conversation.
            source_persona_message_id:
                Newly completed persona response.

        Returns:
            Existing or newly completed terminal extraction effect.

        Raises:
            UnsupportedContinuityModeError:
                If the target is not a Storyline scene.
            ExtractionEffectConflictError:
                If the source is no longer active, selected, complete, or owned.
            InvalidMemoryDeltaTargetError:
                If any proposal command is unsupported, omitted, foreign, or stale.
        """

        if target.mode != ContinuityMode.STORYLINE or target.scene_id is None:
            raise UnsupportedContinuityModeError(
                "Memory extraction requires a Storyline scene target"
            )

        effect = self._effects.reserve(
            target.scope, target.scene_id, source_persona_message_id
        )
        if effect.state != ExtractionEffectState.RESERVED:
            return effect

        selection = self._contexts.build(
            target, source_persona_message_id, self._budget
        )
        delta = self._extractor.extract(selection)
        selection.validate_delta(delta)
        provenance = self._extractor.provenance(selection)
        self._validate_proposal(selection, delta, provenance)

        try:
            return self._effects.apply(effect.id, delta, provenance)
        except ExtractionEffectConflictError:
            current = self._effects.get_effect(target.scope, source_persona_message_id)
            if current is not None and current.state != ExtractionEffectState.RESERVED:
                return current

            raise

    def _validate_proposal(
        self,
        selection: MemorySelectionResult,
        delta: MemoryDelta,
        provenance: ExtractionProvenance,
    ) -> None:
        """Reconcile every command with current state before atomic application.

        Args:
            selection:
                Exact immutable snapshot supplied to the provider.
            delta:
                Complete untrusted provider proposal.
            provenance:
                Extractor-reported configuration, checked against every command.

        Raises:
            InvalidMemoryDeltaTargetError:
                If evidence, content, ownership, or current state is inconsistent.
            MemorySubjectConflictError:
                If a create or replacement collides with another lineage.
            ProtectedMemoryCorrectionError:
                If automatic extraction would replace user-authored content.
        """

        if (
            delta.extractor != self._extractor.strategy_id
            or provenance.extractor != delta.extractor
            or provenance.selector != selection.selector
        ):
            raise InvalidMemoryDeltaTargetError(
                "Delta provenance does not match the configured strategies"
            )

        current = {
            memory.id: memory
            for memory in self._memories.list(selection.context.scope.continuity_id)
        }
        subjects = {
            memory.current.subject.casefold(): memory.id for memory in current.values()
        }
        evidence_ids: set[UUID] = set()
        for command in delta.commands:
            if command.operation == "no_change":
                continue
            if command.evidence.extraction != provenance:
                raise InvalidMemoryDeltaTargetError(
                    "Delta evidence does not match extractor provenance"
                )
            if command.evidence.id in evidence_ids:
                raise InvalidMemoryDeltaTargetError(
                    "Delta evidence identifiers must be unique"
                )
            evidence_ids.add(command.evidence.id)

            if command.operation == "create":
                if command.subject.casefold() in subjects:
                    raise MemorySubjectConflictError(
                        "A logical memory already owns the normalized subject"
                    )

                subjects[command.subject.casefold()] = command.evidence.id
                continue

            target_id = getattr(command, "target_memory_id", None)
            if target_id is None:
                continue

            target = current.get(target_id)
            if target is None:
                raise InvalidMemoryDeltaTargetError(
                    "Memory target is foreign, missing, or stale"
                )

            self._validate_target(command, target, subjects)

    @staticmethod
    def _validate_target(
        command: (
            ReinforceMemoryCommand
            | SupersedeMemoryCommand
            | RecordMemoryConflictCommand
        ),
        target: StorylineMemory,
        subjects: dict[str, UUID],
    ) -> None:
        """Validate one targeted command against a fresh current lineage.

        Args:
            command:
                Reinforce, supersede, or targeted conflict proposal.
            target:
                Fresh current logical-memory snapshot.
            subjects:
                Current normalized-subject ownership map.

        Raises:
            InvalidMemoryDeltaTargetError:
                If the revision, lifecycle, or reinforcement content changed.
            MemorySubjectConflictError:
                If a replacement subject belongs to another lineage.
            ProtectedMemoryCorrectionError:
                If a replacement targets user-authored content.
        """

        if (
            target.current.id != command.expected_revision_id
            or target.current.state != MemoryRevisionState.ACTIVE
        ):
            raise InvalidMemoryDeltaTargetError(
                "Memory target is excluded, superseded, or stale"
            )

        if command.operation == "reinforce" and (
            target.current.content != command.content
        ):
            raise InvalidMemoryDeltaTargetError(
                "Reinforcement must preserve current content"
            )

        if command.operation != "supersede":
            return

        if target.current.authorship == MemoryAuthorship.USER:
            raise ProtectedMemoryCorrectionError(
                "Automatic extraction cannot supersede user content"
            )

        subject = command.subject.casefold()
        owner = subjects.get(subject)
        if owner is not None and owner != target.id:
            raise MemorySubjectConflictError(
                "Another logical memory owns the replacement subject"
            )

        subjects.pop(target.current.subject.casefold(), None)
        subjects[subject] = target.id
