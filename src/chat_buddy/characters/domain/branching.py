"""Immutable message-graph, retry, provenance, and branching contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chat_buddy.characters.domain.continuity import ContinuityMode
from chat_buddy.characters.domain.conversation import ConversationScope
from chat_buddy.characters.domain.evolution import EvolutionStrategyId
from chat_buddy.characters.domain.llm import EffectiveGeneration


class ResponseStyleSnapshot(BaseModel):
    """Fixed response-presentation behavior copied to a persona message.

    Attributes:
        name:
            Stable machine-readable style name.
        version:
            Semantic version of the style behavior.
        instruction:
            Exact non-secret instruction effective for the response.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_.-]*$",
        description="Stable machine-readable style name.",
    )
    version: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$",
        description="Semantic style behavior version.",
    )
    instruction: str = Field(
        min_length=1,
        max_length=4096,
        pattern=r"\S",
        description="Exact effective response instruction.",
    )


class ResponseProvenance(BaseModel):
    """Immutable provenance copied to a completed persona message.

    Attributes:
        generation:
            Effective provider, model, configuration, capability, and budget.
        response_style:
            Fixed response-presentation snapshot.
        evolution_strategy:
            Configured persona-evolution strategy name and version.
        attempt_id:
            Generation attempt that completed the message.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    generation: EffectiveGeneration = Field(
        description="Effective response generation and budget."
    )
    response_style: ResponseStyleSnapshot = Field(
        description="Effective response-presentation behavior."
    )
    evolution_strategy: EvolutionStrategyId = Field(
        description="Configured persona-evolution strategy."
    )
    attempt_id: UUID = Field(description="Completing generation attempt.")

    @model_validator(mode="after")
    def validate_response_capability(self) -> Self:
        """Require response rather than utility-generation provenance.

        Returns:
            Validated provenance.

        Raises:
            ValueError:
                If the generation snapshot is not for a response.
        """

        if self.generation.capability != "response":
            raise ValueError(
                "Persona response provenance requires response generation."
            )
        return self


class MessageNode(BaseModel):
    """One immutable node in an owned conversation graph.

    Attributes:
        id:
            Stable message identifier.
        scope:
            Complete conversation ownership.
        parent_id:
            Immediate parent, or the implicit root when absent.
        role:
            User or persona speaker.
        content:
            Exact committed content.
        created_at:
            Commit timestamp in UTC.
        response_provenance:
            Required completion provenance for persona nodes only.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(description="Stable message identifier.")
    scope: ConversationScope = Field(description="Complete ownership.")
    parent_id: UUID | None = Field(description="Immediate parent message.")
    role: Literal["user", "persona"] = Field(description="Speaker.")
    content: str = Field(min_length=1, pattern=r"\S", description="Committed text.")
    created_at: datetime = Field(description="UTC commit timestamp.")
    response_provenance: ResponseProvenance | None = Field(
        default=None, description="Persona response provenance."
    )

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        """Require provenance exactly on completed persona nodes.

        Returns:
            Validated node.

        Raises:
            ValueError:
                If provenance and role disagree.
        """

        if (self.role == "persona") != (self.response_provenance is not None):
            raise ValueError("Only persona nodes require response provenance.")
        return self


class SelectedPath(BaseModel):
    """Selected root-to-leaf ancestry in chronological parent order.

    Attributes:
        scope:
            Complete conversation ownership.
        selected_leaf_id:
            Selected final node, or none for an empty conversation.
        messages:
            Exact root-to-leaf ancestry.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ConversationScope = Field(description="Complete ownership.")
    selected_leaf_id: UUID | None = Field(description="Selected final node.")
    messages: tuple[MessageNode, ...] = Field(
        description="Root-to-leaf parent ancestry."
    )

    @model_validator(mode="after")
    def validate_path(self) -> Self:
        """Validate ownership, root, edges, uniqueness, and selected leaf.

        Returns:
            Validated selected path.

        Raises:
            ValueError:
                If messages do not form one owned alternating parent chain.
        """

        if not self.messages:
            if self.selected_leaf_id is not None:
                raise ValueError("An empty path cannot have a selected leaf.")
            return self
        if self.selected_leaf_id != self.messages[-1].id:
            raise ValueError("The selected leaf must be the final path node.")
        if self.messages[0].parent_id is not None or self.messages[0].role != "user":
            raise ValueError("A selected path must start with a root user node.")
        if len({message.id for message in self.messages}) != len(self.messages):
            raise ValueError("A selected path cannot contain a cycle.")
        for parent, child in zip(self.messages, self.messages[1:], strict=False):
            if child.scope != self.scope or child.parent_id != parent.id:
                raise ValueError("Each path edge must use the supplied ownership.")
            if child.role == parent.role:
                raise ValueError("Message roles must alternate on every path edge.")
        if self.messages[0].scope != self.scope:
            raise ValueError("Every path node must use the supplied ownership.")
        return self


class ConversationGraph(BaseModel):
    """Detached graph inspection snapshot, separate from selected-path reads.

    Attributes:
        scope:
            Complete conversation ownership.
        selected_leaf_id:
            Selected node, or none for an empty graph.
        nodes:
            Every graph node in deterministic sibling order.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ConversationScope = Field(description="Complete ownership.")
    selected_leaf_id: UUID | None = Field(description="Selected node.")
    nodes: tuple[MessageNode, ...] = Field(description="All conversation nodes.")

    @model_validator(mode="after")
    def validate_graph(self) -> Self:
        """Validate graph ownership, edges, roles, cycles, and ordering.

        Returns:
            Validated graph.

        Raises:
            ValueError:
                If the snapshot is not one owned alternating acyclic graph.
        """

        by_id = {node.id: node for node in self.nodes}
        if len(by_id) != len(self.nodes):
            raise ValueError("Graph message identifiers must be unique.")
        if self.selected_leaf_id is not None and self.selected_leaf_id not in by_id:
            raise ValueError("The selected leaf must exist in the graph.")
        if not self.nodes and self.selected_leaf_id is not None:
            raise ValueError("An empty graph cannot have a selected leaf.")
        order = tuple((node.created_at, str(node.id)) for node in self.nodes)
        if order != tuple(sorted(order)):
            raise ValueError("Graph nodes must use deterministic creation ordering.")
        for node in self.nodes:
            if node.scope != self.scope:
                raise ValueError("Every graph node must use the supplied ownership.")
            if node.parent_id is None:
                if node.role != "user":
                    raise ValueError("Root children must be user nodes.")
                continue
            parent = by_id.get(node.parent_id)
            if parent is None or parent.scope != node.scope:
                raise ValueError("Every parent must exist in the same scope.")
            if parent.role == node.role:
                raise ValueError("Message roles must alternate on every graph edge.")
            seen = {node.id}
            ancestor = parent
            while ancestor.parent_id is not None:
                if ancestor.id in seen:
                    raise ValueError("Conversation graphs cannot contain cycles.")
                seen.add(ancestor.id)
                next_ancestor = by_id.get(ancestor.parent_id)
                if next_ancestor is None:
                    raise ValueError("Every ancestor must exist in the graph.")
                ancestor = next_ancestor
            if ancestor.id in seen:
                raise ValueError("Conversation graphs cannot contain cycles.")
        return self

    def selected_path(self) -> SelectedPath:
        """Derive selected order exclusively through parent traversal.

        Returns:
            Empty or root-to-selected-leaf ancestry.
        """

        if self.selected_leaf_id is None:
            return SelectedPath(scope=self.scope, selected_leaf_id=None, messages=())
        by_id = {node.id: node for node in self.nodes}
        current = by_id[self.selected_leaf_id]
        reversed_path = [current]
        while current.parent_id is not None:
            current = by_id[current.parent_id]
            reversed_path.append(current)
        return SelectedPath(
            scope=self.scope,
            selected_leaf_id=self.selected_leaf_id,
            messages=tuple(reversed(reversed_path)),
        )


class GraphNodeView(BaseModel):
    """Detached action metadata for one immutable graph node.

    Attributes:
        message:
            Immutable message represented by this entry.
        alternative_ids:
            Deterministically ordered persona siblings for the same user turn.
        retry_count:
            Successful retries completed for that turn.
        selected:
            Whether the node belongs to the selected ancestry.
        selected_leaf:
            Whether the node is the exact selected leaf.
        branchable:
            Whether an in-place branch may start from this node now.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: MessageNode = Field(description="Immutable graph message.")
    alternative_ids: tuple[UUID, ...] = Field(
        description="Ordered persona alternatives for the same user turn."
    )
    retry_count: int = Field(
        ge=0, le=3, description="Successful retry count for the user turn."
    )
    selected: bool = Field(description="Whether the node is on the selected path.")
    selected_leaf: bool = Field(description="Whether this node is selected exactly.")
    branchable: bool = Field(description="Whether branching is currently allowed.")

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        """Keep view flags and alternative metadata internally consistent.

        Returns:
            Validated graph-node view.

        Raises:
            ValueError:
                If flags or alternative metadata contradict the message.
        """

        if self.selected_leaf and not self.selected:
            raise ValueError("The selected leaf must belong to the selected path.")
        if self.branchable and (
            self.message.role != "persona" or not self.selected or self.selected_leaf
        ):
            raise ValueError("Only older selected-path persona nodes are branchable.")
        if self.message.role == "user":
            if self.alternative_ids or self.retry_count:
                raise ValueError("User nodes do not carry persona alternatives.")
        elif self.message.id not in self.alternative_ids:
            raise ValueError("A persona node must appear in its alternatives.")
        elif self.retry_count != len(self.alternative_ids) - 1:
            raise ValueError("Retry count must derive from completed alternatives.")
        return self


class ConversationGraphView(BaseModel):
    """Deterministic detached graph inspection prepared for user actions.

    Attributes:
        scope:
            Complete conversation ownership.
        selected_leaf_id:
            Exact selected persona leaf, or none for an empty graph.
        nodes:
            Every graph node with derived selection and action metadata.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ConversationScope = Field(description="Complete ownership.")
    selected_leaf_id: UUID | None = Field(description="Selected graph leaf.")
    nodes: tuple[GraphNodeView, ...] = Field(
        description="Deterministically ordered graph-node views."
    )

    @model_validator(mode="after")
    def validate_view(self) -> Self:
        """Require owned deterministic nodes and one matching selected leaf.

        Returns:
            Validated graph view.

        Raises:
            ValueError:
                If ownership, ordering, or selected state is inconsistent.
        """

        if any(node.message.scope != self.scope for node in self.nodes):
            raise ValueError("Every graph-view node must use the supplied ownership.")
        order = tuple(
            (node.message.created_at, str(node.message.id)) for node in self.nodes
        )
        if order != tuple(sorted(order)):
            raise ValueError("Graph-view nodes must use deterministic ordering.")
        selected_leaves = tuple(node for node in self.nodes if node.selected_leaf)
        if self.selected_leaf_id is None:
            if selected_leaves:
                raise ValueError("An empty selection cannot mark a selected leaf.")
        elif (
            len(selected_leaves) != 1
            or selected_leaves[0].message.id != self.selected_leaf_id
        ):
            raise ValueError("The graph view must mark its exact selected leaf.")
        return self


class AlternativeGroup(BaseModel):
    """Completed persona alternatives for one user parent.

    Attributes:
        scope:
            Complete conversation ownership.
        user_message_id:
            Shared user parent.
        responses:
            One initial response and up to three successful retries.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ConversationScope = Field(description="Complete ownership.")
    user_message_id: UUID = Field(description="Shared user parent.")
    responses: tuple[MessageNode, ...] = Field(
        min_length=1,
        max_length=4,
        description="Deterministically ordered persona alternatives.",
    )

    @model_validator(mode="after")
    def validate_alternatives(self) -> Self:
        """Require owned persona siblings in deterministic order.

        Returns:
            Validated alternative group.

        Raises:
            ValueError:
                If responses are not ordered siblings in the supplied scope.
        """

        if any(
            response.scope != self.scope
            or response.role != "persona"
            or response.parent_id != self.user_message_id
            for response in self.responses
        ):
            raise ValueError("Alternatives must be owned persona siblings.")
        order = tuple(
            (response.created_at, str(response.id)) for response in self.responses
        )
        if order != tuple(sorted(order)):
            raise ValueError("Alternatives must use deterministic creation ordering.")
        return self


class RetryAvailability(BaseModel):
    """Durable successful-response accounting for one user turn.

    Attributes:
        user_message_id:
            User node whose persona responses are counted.
        successful_response_count:
            Initial completed response plus successful retries.
        maximum_retries:
            Stable successful-retry allowance.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_message_id: UUID = Field(description="Parent user message.")
    successful_response_count: int = Field(
        ge=1, le=4, description="Completed persona sibling count."
    )
    maximum_retries: Literal[3] = Field(
        default=3, description="Maximum successful retries."
    )

    @property
    def retries_used(self) -> int:
        """Return completed alternatives beyond the initial response.

        Returns:
            Successful retries already consumed.
        """

        return self.successful_response_count - 1

    @property
    def retries_remaining(self) -> int:
        """Return successful retry slots still available.

        Returns:
            Remaining retry allowance.
        """

        return self.maximum_retries - self.retries_used


class GraphAction(StrEnum):
    """Distinct generation and graph-selection operations."""

    INITIAL_GENERATION = "initial_generation"
    INCOMPLETE_CONTINUATION = "incomplete_continuation"
    COMPLETED_RESPONSE_RETRY = "completed_response_retry"
    ALTERNATIVE_SELECTION = "alternative_selection"
    BRANCH_FROM_HERE = "branch_from_here"


class GraphActionRequest(BaseModel):
    """Guarded request for one explicitly classified graph operation.

    Attributes:
        scope:
            Complete conversation ownership.
        action:
            Exact operation semantics.
        expected_selected_leaf_id:
            Last selected leaf observed by the caller.
        target_message_id:
            Exact existing target for non-initial operations.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ConversationScope = Field(description="Complete ownership.")
    action: GraphAction = Field(description="Requested graph operation.")
    expected_selected_leaf_id: UUID | None = Field(
        description="Compare-and-swap selected leaf."
    )
    target_message_id: UUID | None = Field(description="Exact target message.")

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        """Separate initial generation from targeted recovery and graph actions.

        Returns:
            Validated action request.

        Raises:
            ValueError:
                If target shape contradicts the action.
        """

        if self.action == GraphAction.INITIAL_GENERATION:
            if self.target_message_id is not None:
                raise ValueError("Initial generation has no existing target.")
        elif self.target_message_id is None or self.expected_selected_leaf_id is None:
            raise ValueError(
                "Existing-message actions require a target and leaf guard."
            )
        return self


class BranchModeFacts(BaseModel):
    """Persistence-neutral mode facts needed to authorize branching.

    Attributes:
        scope:
            Exact source conversation references.
        source_message_id:
            Exact persona branch point.
        mode:
            Continuity mode governing the operation.
        storyline_has_later_scenes:
            Whether a Storyline source scene has dependent later scenes.
        timeline_day_closed:
            Whether a Timeline source day is closed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ConversationScope = Field(description="Exact source ownership.")
    source_message_id: UUID = Field(description="Exact source branch point.")
    mode: ContinuityMode = Field(description="Governing continuity mode.")
    storyline_has_later_scenes: bool | None = Field(
        default=None, description="Storyline dependent-scene fact."
    )
    timeline_day_closed: bool | None = Field(
        default=None, description="Timeline closure fact."
    )


class BranchDecision(BaseModel):
    """Fail-closed mode-policy result with exact source references.

    Attributes:
        disposition:
            In-place authorization or required future workflow fork.
        scope:
            Exact source conversation references.
        source_message_id:
            Exact source branch point.
        reason:
            Stable machine-readable policy explanation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    disposition: Literal["in_place", "fork_required"] = Field(
        description="Authorized mutation location."
    )
    scope: ConversationScope = Field(description="Exact source ownership.")
    source_message_id: UUID = Field(description="Exact source branch point.")
    reason: Literal[
        "ongoing",
        "latest_storyline_scene",
        "older_storyline_scene",
        "open_timeline_day",
        "closed_timeline_day",
        "missing_or_contradictory_mode_facts",
    ] = Field(description="Policy reason.")
