"""Immutable message-graph, retry, action, and provenance contracts."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from chat_buddy.characters.domain import (
    AlternativeGroup,
    ConversationGraph,
    ConversationGraphRepository,
    ConversationScope,
    EffectiveGeneration,
    EvolutionStrategyId,
    GenerationConfiguration,
    GraphAction,
    GraphActionRequest,
    MessageNode,
    ModelDescriptor,
    ResponseProvenance,
    ResponseStyleSnapshot,
    RetryAvailability,
    SelectedPath,
)


def _scope() -> ConversationScope:
    """Create one complete graph ownership scope.

    Returns:
        Stable-shape scope with generated identifiers.
    """

    return ConversationScope(
        identity_id=uuid4(),
        persona_id=uuid4(),
        continuity_id=uuid4(),
        conversation_id=uuid4(),
    )


def _provenance() -> ResponseProvenance:
    """Create complete immutable response provenance.

    Returns:
        Valid response generation, style, strategy, and attempt data.
    """

    descriptor = ModelDescriptor(
        provider="fake",
        model="first",
        context_tokens=8192,
        output_tokens=128,
        capabilities=frozenset({"response"}),
        parameters=frozenset({"temperature"}),
    )
    return ResponseProvenance(
        generation=EffectiveGeneration(
            model=descriptor,
            configuration=GenerationConfiguration(
                max_output_tokens=128, temperature=0.4
            ),
            capability="response",
            input_tokens=8064,
        ),
        response_style=ResponseStyleSnapshot(
            name="ongoing.default",
            version="1.0.0",
            instruction="Respond naturally while preserving authored boundaries.",
        ),
        evolution_strategy=EvolutionStrategyId(
            name="baseline.no_change", version="1.0.0"
        ),
        attempt_id=uuid4(),
    )


def _node(
    scope: ConversationScope,
    *,
    role: Literal["user", "persona"],
    parent_id: UUID | None,
    created_at: datetime,
) -> MessageNode:
    """Create a valid user or persona graph node.

    Args:
        scope:
            Complete message ownership.
        role:
            User or persona role.
        parent_id:
            Immediate parent, absent at the implicit root.
        created_at:
            Deterministic commit timestamp.

    Returns:
        Valid immutable node.
    """

    return MessageNode(
        id=uuid4(),
        scope=scope,
        parent_id=parent_id,
        role=role,
        content=f"{role} content",
        created_at=created_at,
        response_provenance=_provenance() if role == "persona" else None,
    )


def test_graph_derives_selected_order_from_parents_and_omits_siblings() -> None:
    """Traverse parents rather than relying on a persisted sequence or depth."""

    scope = _scope()
    now = datetime.now(UTC)
    user = _node(scope, role="user", parent_id=None, created_at=now)
    selected = _node(
        scope, role="persona", parent_id=user.id, created_at=now + timedelta(seconds=1)
    )
    sibling = _node(
        scope, role="persona", parent_id=user.id, created_at=now + timedelta(seconds=2)
    )
    graph = ConversationGraph(
        scope=scope,
        selected_leaf_id=selected.id,
        nodes=(user, selected, sibling),
    )

    assert graph.selected_path().messages == (user, selected)
    assert "sequence" not in MessageNode.model_fields
    assert "depth" not in MessageNode.model_fields


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("foreign_scope", "supplied ownership"),
        ("second_root", "path edge"),
        ("same_role", "alternate"),
        ("cycle", "cycle"),
    ],
)
def test_selected_path_rejects_invalid_ownership_roots_roles_and_cycles(
    mutation: str, message: str
) -> None:
    """Reject malformed selected ancestry.

    Args:
        mutation:
            Invalid path shape to construct.
        message:
            Expected validation explanation.
    """

    scope = _scope()
    now = datetime.now(UTC)
    first = _node(scope, role="user", parent_id=None, created_at=now)
    second = _node(
        scope,
        role="persona",
        parent_id=first.id,
        created_at=now + timedelta(seconds=1),
    )
    messages: tuple[MessageNode, ...] = (first, second)
    selected_leaf_id = second.id
    if mutation == "foreign_scope":
        messages = (first, second.model_copy(update={"scope": _scope()}))
    elif mutation == "second_root":
        messages = (first, second.model_copy(update={"parent_id": None}))
    elif mutation == "same_role":
        messages = (
            first,
            first.model_copy(
                update={
                    "id": uuid4(),
                    "parent_id": first.id,
                    "created_at": second.created_at,
                }
            ),
        )
        selected_leaf_id = messages[-1].id
    else:
        messages = (first, second, first)
        selected_leaf_id = first.id
    with pytest.raises(ValidationError, match=message):
        SelectedPath(
            scope=scope,
            selected_leaf_id=selected_leaf_id,
            messages=messages,
        )


def test_graph_rejects_foreign_parent_and_persona_root() -> None:
    """Require same-scope existing parents and user nodes at the implicit root."""

    scope = _scope()
    now = datetime.now(UTC)
    foreign_parent = _node(_scope(), role="user", parent_id=None, created_at=now)
    child = _node(
        scope,
        role="persona",
        parent_id=foreign_parent.id,
        created_at=now + timedelta(seconds=1),
    )
    with pytest.raises(ValidationError, match="supplied ownership"):
        ConversationGraph(
            scope=scope,
            selected_leaf_id=child.id,
            nodes=(foreign_parent, child),
        )
    root_persona = _node(scope, role="persona", parent_id=None, created_at=now)
    with pytest.raises(ValidationError, match="Root children"):
        ConversationGraph(
            scope=scope,
            selected_leaf_id=root_persona.id,
            nodes=(root_persona,),
        )


def test_response_provenance_and_graph_values_are_frozen() -> None:
    """Capture exact completion provenance and reject mutation or utility output."""

    provenance = _provenance()
    assert provenance.generation.model.provider == "fake"
    assert provenance.generation.model.model == "first"
    assert provenance.generation.configuration.max_output_tokens == 128
    assert provenance.generation.input_tokens == 8064
    assert provenance.response_style.name == "ongoing.default"
    assert provenance.evolution_strategy.name == "baseline.no_change"
    with pytest.raises(ValidationError):
        provenance.attempt_id = uuid4()
    with pytest.raises(ValidationError, match="response generation"):
        summary_descriptor = provenance.generation.model.model_copy(
            update={"capabilities": frozenset({"response", "summary"})}
        )
        ResponseProvenance(
            generation=provenance.generation.model_copy(
                update={"model": summary_descriptor, "capability": "summary"}
            ),
            response_style=provenance.response_style,
            evolution_strategy=provenance.evolution_strategy,
            attempt_id=uuid4(),
        )


def test_alternatives_and_retry_availability_count_only_completed_siblings() -> None:
    """Expose one initial response plus exactly three successful retry slots."""

    scope = _scope()
    now = datetime.now(UTC)
    parent_id = uuid4()
    responses = tuple(
        _node(
            scope,
            role="persona",
            parent_id=parent_id,
            created_at=now + timedelta(seconds=index),
        )
        for index in range(4)
    )
    group = AlternativeGroup(
        scope=scope, user_message_id=parent_id, responses=responses
    )
    availability = RetryAvailability(
        user_message_id=parent_id,
        successful_response_count=len(group.responses),
    )

    assert availability.retries_used == 3
    assert availability.retries_remaining == 0
    with pytest.raises(ValidationError):
        RetryAvailability(user_message_id=parent_id, successful_response_count=5)


@pytest.mark.parametrize(
    "action",
    [
        GraphAction.INCOMPLETE_CONTINUATION,
        GraphAction.COMPLETED_RESPONSE_RETRY,
        GraphAction.ALTERNATIVE_SELECTION,
        GraphAction.BRANCH_FROM_HERE,
    ],
)
def test_action_contract_distinguishes_targeted_operations(action: GraphAction) -> None:
    """Keep continuation, retry, selection, and branching semantically distinct.

    Args:
        action:
            Existing-message operation under test.
    """

    target = uuid4()
    request = GraphActionRequest(
        scope=_scope(),
        action=action,
        expected_selected_leaf_id=uuid4(),
        target_message_id=target,
    )
    assert request.action == action
    assert request.target_message_id == target


def test_initial_generation_has_no_existing_target() -> None:
    """Keep a new input separate from continuation and completed-response retry."""

    request = GraphActionRequest(
        scope=_scope(),
        action=GraphAction.INITIAL_GENERATION,
        expected_selected_leaf_id=None,
        target_message_id=None,
    )
    assert request.action == GraphAction.INITIAL_GENERATION
    with pytest.raises(ValidationError, match="no existing target"):
        GraphActionRequest(
            scope=request.scope,
            action=request.action,
            expected_selected_leaf_id=None,
            target_message_id=uuid4(),
        )


def test_repository_contract_separates_path_reads_from_graph_inspection() -> None:
    """Prevent ordinary selected-history reads from accidentally exposing siblings."""

    assert callable(ConversationGraphRepository.selected_path)
    assert callable(ConversationGraphRepository.graph)
