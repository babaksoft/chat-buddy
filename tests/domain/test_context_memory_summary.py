from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    CompletedTurn,
    ContextAssemblyResult,
    ContextBudgeter,
    ContextEligibility,
    ContextInputs,
    ExtractionReceiptRecord,
    GenerationConfiguration,
    MemoryCandidate,
    MemoryExtractionOutcome,
    MemoryLifecycle,
    MemoryOrigin,
    MemoryOriginKind,
    MemoryRecord,
    ModelDescriptor,
    SummaryLifecycle,
    SummaryProvenance,
    SummaryRecord,
)

NOW = datetime(2026, 9, 18, tzinfo=UTC)


class FakeEligibility:
    """Eligibility fake that deliberately has no token counter."""

    def get_inputs(
        self, conversation_id: UUID, current_input: ChatMessage
    ) -> ContextInputs:
        """Return supplied current input as eligible context.

        Args:
            conversation_id:
                Conversation identifier supplied by the caller.
            current_input:
                Current user input supplied by the caller.

        Returns:
            Context inputs containing no repository-loaded components.
        """

        return ContextInputs(conversation_id, current_input)


class FakeBudgeter:
    """Budget fake that deliberately has no repository."""

    def assemble(
        self,
        inputs: ContextInputs,
        model: ModelDescriptor,
        configuration: GenerationConfiguration,
    ) -> ContextAssemblyResult:
        """Assemble only the current input without querying persistence.

        Args:
            inputs:
                Eligible context inputs to assemble.
            model:
                Selected model, unused by this fake.
            configuration:
                Effective generation settings, unused by this fake.

        Returns:
            Single-message assembly result for the current input.
        """

        return ContextAssemblyResult((inputs.current_input,), 1, 1)


def _extracted_origin() -> MemoryOrigin:
    """Create complete extracted provenance for tests.

    Returns:
        Valid extracted provenance.
    """

    return MemoryOrigin(
        kind=MemoryOriginKind.EXTRACTED,
        conversation_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        generation_attempt_id=uuid4(),
    )


def _memory(
    lifecycle: MemoryLifecycle = MemoryLifecycle.ACTIVE,
) -> MemoryRecord:
    """Create a valid memory revision for tests.

    Args:
        lifecycle:
            Lifecycle assigned to the revision.

    Returns:
        Valid memory revision.
    """

    return MemoryRecord(
        id=uuid4(),
        revision_id=uuid4(),
        subject="favorite language",
        content="Python",
        lifecycle=lifecycle,
        origin=_extracted_origin(),
        created_at=NOW,
        updated_at=NOW,
    )


def _turn(conversation_id: UUID) -> CompletedTurn:
    """Create a valid completed turn for tests.

    Args:
        conversation_id:
            Owning conversation identifier.

    Returns:
        Valid completed turn.
    """

    return CompletedTurn(
        conversation_id=conversation_id,
        attempt_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        user_content="Hello",
        assistant_content="Hi",
        completed_at=NOW,
    )


def _summary(
    conversation_id: UUID,
    lifecycle: SummaryLifecycle = SummaryLifecycle.ACTIVE,
    predecessor_id: UUID | None = None,
) -> SummaryRecord:
    """Create a valid summary version for tests.

    Args:
        conversation_id:
            Owning conversation identifier.
        lifecycle:
            Lifecycle assigned to the version.
        predecessor_id:
            Optional prior summary identifier.

    Returns:
        Valid summary version.
    """

    summary_id = uuid4()
    return SummaryRecord(
        id=summary_id,
        conversation_id=conversation_id,
        content="Earlier conversation",
        created_at=NOW,
        lifecycle=lifecycle,
        provenance=SummaryProvenance(
            conversation_id=conversation_id,
            checkpoint_message_id=uuid4(),
            predecessor_id=predecessor_id,
        ),
    )


def test_summary_is_immutable_and_active_summary_can_be_superseded() -> None:
    """Summary versions are immutable and permit only active-to-superseded."""

    summary = _summary(uuid4())

    assert summary.supersede().lifecycle is SummaryLifecycle.SUPERSEDED
    with pytest.raises(ValueError, match="Only an active"):
        summary.supersede().supersede()
    with pytest.raises(FrozenInstanceError):
        summary.content = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"content": "  "}, "content"),
        ({"created_at": datetime(2026, 1, 1)}, "timezone-aware"),  # noqa: DTZ001
        ({"id": UUID(int=0)}, "nil UUID"),
    ],
)
def test_summary_rejects_invalid_values(
    changes: dict[str, object], message: str
) -> None:
    """Summary validation rejects malformed identity, text, and time.

    Args:
        changes:
            Constructor values replacing valid defaults.
        message:
            Expected validation diagnostic.
    """

    conversation_id = uuid4()
    values: dict[str, object] = {
        "id": uuid4(),
        "conversation_id": conversation_id,
        "content": "Summary",
        "created_at": NOW,
        "lifecycle": SummaryLifecycle.ACTIVE,
        "provenance": SummaryProvenance(
            conversation_id=conversation_id,
            checkpoint_message_id=uuid4(),
        ),
    }
    values.update(changes)

    with pytest.raises(ValueError, match=message):
        SummaryRecord(**values)  # type: ignore[arg-type]


def test_summary_provenance_rejects_cross_conversation_ownership() -> None:
    """Summary ownership must agree with its compact checkpoint provenance."""

    conversation_id = uuid4()
    valid_provenance = SummaryProvenance(
        conversation_id=conversation_id,
        checkpoint_message_id=uuid4(),
    )
    with pytest.raises(ValueError, match="another conversation"):
        SummaryRecord(
            id=uuid4(),
            conversation_id=uuid4(),
            content="Summary",
            created_at=NOW,
            lifecycle=SummaryLifecycle.ACTIVE,
            provenance=valid_provenance,
        )


def test_summary_provenance_tracks_checkpoint_progression_without_source_graph() -> (
    None
):
    """Successors carry only predecessor and authoritative assistant checkpoint."""

    predecessor_id = uuid4()
    checkpoint_id = uuid4()
    provenance = SummaryProvenance(
        conversation_id=uuid4(),
        checkpoint_message_id=checkpoint_id,
        predecessor_id=predecessor_id,
    )

    assert provenance.predecessor_id == predecessor_id
    assert provenance.checkpoint_message_id == checkpoint_id
    assert not hasattr(provenance, "newly_covered_sources")


@pytest.mark.parametrize(
    ("outcome", "attempt_count"),
    [
        (MemoryExtractionOutcome.SUCCEEDED, 1),
        (MemoryExtractionOutcome.SUCCEEDED, 3),
        (MemoryExtractionOutcome.EXHAUSTED, 3),
    ],
)
def test_extraction_receipt_accepts_terminal_bounded_outcomes(
    outcome: MemoryExtractionOutcome, attempt_count: int
) -> None:
    """Receipts represent only bounded succeeded or exhausted processing.

    Args:
        outcome:
            Terminal processing outcome.
        attempt_count:
            Number of complete processing attempts consumed.
    """

    receipt = ExtractionReceiptRecord(uuid4(), outcome, attempt_count, NOW)

    assert receipt.outcome is outcome
    assert receipt.attempt_count == attempt_count


@pytest.mark.parametrize(
    ("outcome", "attempt_count"),
    [
        (MemoryExtractionOutcome.SUCCEEDED, 0),
        (MemoryExtractionOutcome.SUCCEEDED, 4),
        (MemoryExtractionOutcome.EXHAUSTED, 2),
    ],
)
def test_extraction_receipt_rejects_invalid_attempt_counts(
    outcome: MemoryExtractionOutcome, attempt_count: int
) -> None:
    """Receipts enforce the three-attempt processing bound.

    Args:
        outcome:
            Terminal processing outcome.
        attempt_count:
            Invalid processing count.
    """

    with pytest.raises(ValueError, match="attempt"):
        ExtractionReceiptRecord(uuid4(), outcome, attempt_count, NOW)


def test_memory_candidate_requires_normalized_subject_and_content() -> None:
    """Candidates reject unnormalized or empty extractor output."""

    assert MemoryCandidate("favorite language", "Python").content == "Python"
    with pytest.raises(ValueError, match="subject"):
        MemoryCandidate("Favorite   Language", "Python")
    with pytest.raises(ValueError, match="content"):
        MemoryCandidate("editor", " VS  Code ")
    with pytest.raises(ValueError, match="non-empty"):
        MemoryCandidate("", "Python")


def test_extracted_origin_requires_all_or_no_source_identifiers() -> None:
    """Extracted provenance is complete while available and empty when cleared."""

    assert _extracted_origin().source_available is True
    unavailable = MemoryOrigin(
        kind=MemoryOriginKind.EXTRACTED,
        source_available=False,
    )
    assert unavailable.conversation_id is None

    with pytest.raises(ValueError, match="complete source"):
        MemoryOrigin(
            kind=MemoryOriginKind.EXTRACTED,
            conversation_id=uuid4(),
        )
    with pytest.raises(ValueError, match="clear source"):
        MemoryOrigin(
            kind=MemoryOriginKind.EXTRACTED,
            source_available=False,
            conversation_id=uuid4(),
        )


def test_correction_origin_rejects_extraction_fields_and_naive_time() -> None:
    """Correction provenance identifies only its prior revision and local time."""

    origin = MemoryOrigin(
        kind=MemoryOriginKind.USER_CORRECTION,
        superseded_revision_id=uuid4(),
        corrected_at=NOW,
    )
    assert origin.kind is MemoryOriginKind.USER_CORRECTION

    with pytest.raises(ValueError, match="cannot contain extraction"):
        MemoryOrigin(
            kind=MemoryOriginKind.USER_CORRECTION,
            conversation_id=uuid4(),
            superseded_revision_id=uuid4(),
            corrected_at=NOW,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        MemoryOrigin(
            kind=MemoryOriginKind.USER_CORRECTION,
            superseded_revision_id=uuid4(),
            corrected_at=datetime(2026, 1, 1),  # noqa: DTZ001
        )


def test_memory_allows_every_legal_lifecycle_transition() -> None:
    """Active memories may exclude or supersede and excluded memories reactivate."""

    memory = _memory()

    assert (
        memory.transition(MemoryLifecycle.EXCLUDED, at=NOW).lifecycle
        is MemoryLifecycle.EXCLUDED
    )
    assert (
        memory.transition(MemoryLifecycle.SUPERSEDED, at=NOW).lifecycle
        is MemoryLifecycle.SUPERSEDED
    )
    assert (
        _memory(MemoryLifecycle.EXCLUDED)
        .transition(MemoryLifecycle.ACTIVE, at=NOW)
        .lifecycle
        is MemoryLifecycle.ACTIVE
    )


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (MemoryLifecycle.ACTIVE, MemoryLifecycle.ACTIVE),
        (MemoryLifecycle.EXCLUDED, MemoryLifecycle.EXCLUDED),
        (MemoryLifecycle.EXCLUDED, MemoryLifecycle.SUPERSEDED),
        (MemoryLifecycle.SUPERSEDED, MemoryLifecycle.ACTIVE),
        (MemoryLifecycle.SUPERSEDED, MemoryLifecycle.EXCLUDED),
        (MemoryLifecycle.SUPERSEDED, MemoryLifecycle.SUPERSEDED),
    ],
)
def test_memory_rejects_every_illegal_lifecycle_transition(
    source: MemoryLifecycle, target: MemoryLifecycle
) -> None:
    """Memory revisions reject idempotent and forbidden state changes.

    Args:
        source:
            Initial lifecycle.
        target:
            Forbidden target lifecycle.
    """

    with pytest.raises(ValueError, match="Cannot transition"):
        _memory(source).transition(target, at=NOW)


def test_memory_rejects_invalid_values_and_transition_time() -> None:
    """Memory snapshots validate normalization, timestamps, and chronology."""

    values: dict[str, object] = {
        "id": uuid4(),
        "revision_id": uuid4(),
        "subject": "Favorite Language",
        "content": "Python",
        "lifecycle": MemoryLifecycle.ACTIVE,
        "origin": _extracted_origin(),
        "created_at": NOW,
        "updated_at": NOW,
    }
    with pytest.raises(ValueError, match="subject"):
        MemoryRecord(**values)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="last update"):
        _memory().transition(
            MemoryLifecycle.EXCLUDED,
            at=NOW - timedelta(seconds=1),
        )


def test_context_inputs_enforce_eligibility_and_conversation_ownership() -> None:
    """Persistence-neutral inputs reject cross-scope and inactive components."""

    conversation_id = uuid4()
    inputs = ContextInputs(
        conversation_id=conversation_id,
        current_input=ChatMessage(ChatRole.USER, "Question"),
        memories=(_memory(),),
        summary=_summary(conversation_id),
        uncovered_turns=(_turn(conversation_id),),
    )
    assert len(inputs.uncovered_turns) == 1

    with pytest.raises(ValueError, match="another conversation"):
        ContextInputs(
            conversation_id=conversation_id,
            current_input=ChatMessage(ChatRole.USER, "Question"),
            summary=_summary(uuid4()),
        )
    with pytest.raises(ValueError, match="active memories"):
        ContextInputs(
            conversation_id=conversation_id,
            current_input=ChatMessage(ChatRole.USER, "Question"),
            memories=(_memory(MemoryLifecycle.EXCLUDED),),
        )


def test_eligibility_and_budget_seams_are_independently_implementable() -> None:
    """Fakes satisfy separate seams without token or repository dependencies."""

    eligibility: ContextEligibility = FakeEligibility()
    budgeter: ContextBudgeter = FakeBudgeter()
    inputs = eligibility.get_inputs(uuid4(), ChatMessage(ChatRole.USER, "Question"))

    assert inputs.current_input.content == "Question"
    assert not hasattr(eligibility, "token_counter")
    assert not hasattr(budgeter, "repository")
