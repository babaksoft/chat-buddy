"""Immutable Storyline ownership, scene, append, and fork contracts."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chat_buddy.characters.domain.branching import ResponseStyleSnapshot
from chat_buddy.characters.domain.continuity import (
    ContinuityLifecycle,
    RelationshipSelection,
    StartingRelationship,
)
from chat_buddy.characters.domain.conversation import ConversationScope


class SceneDetails(BaseModel):
    """Current authored metadata and fixed response style for a scene.

    Attributes:
        title:
            User-authored presentation title.
        setup:
            User-authored situation included in scene prompts.
        response_style:
            Fixed response behavior for every response in the scene.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    title: str = Field(
        min_length=1, max_length=128, description="Presentation-only scene title."
    )
    setup: str = Field(
        min_length=1, max_length=8192, description="Authored scene situation."
    )
    response_style: ResponseStyleSnapshot = Field(
        description="Fixed response behavior for the scene."
    )


class StartStoryline(BaseModel):
    """Complete reviewed input for an idempotent Storyline start.

    Attributes:
        request_id:
            Unique confirmation identifier.
        identity_id:
            Reviewed identity owner.
        persona_id:
            Reviewed persona owner.
        identity_revision:
            Reviewed identity revision.
        persona_revision:
            Reviewed persona revision.
        name:
            User-authored Storyline name.
        relationship:
            Reviewed starting relationship selection.
        initial_scene:
            Authored initial scene definition.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    request_id: UUID = Field(description="Confirmation identifier.")
    identity_id: UUID = Field(description="Reviewed identity identifier.")
    persona_id: UUID = Field(description="Reviewed persona identifier.")
    identity_revision: int = Field(ge=1, description="Reviewed identity revision.")
    persona_revision: int = Field(ge=1, description="Reviewed persona revision.")
    name: str = Field(
        min_length=1, max_length=128, description="Authored Storyline name."
    )
    relationship: RelationshipSelection = Field(
        description="Reviewed relationship inputs."
    )
    initial_scene: SceneDetails = Field(description="Initial scene details.")


class Storyline(BaseModel):
    """Detached named Storyline snapshot with immutable profile ownership.

    Attributes:
        id:
            Stable continuity identifier.
        identity_id:
            Permanent identity owner.
        persona_id:
            Permanent persona owner.
        name:
            Current user-authored name.
        lifecycle:
            Writable or permanently archived state.
        relationship:
            Independent starting relationship snapshot.
        revision:
            Positive optimistic revision for guarded Storyline writes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(description="Stable Storyline continuity identifier.")
    identity_id: UUID = Field(description="Permanent identity owner.")
    persona_id: UUID = Field(description="Permanent persona owner.")
    name: str = Field(
        min_length=1, max_length=128, description="Current Storyline name."
    )
    lifecycle: ContinuityLifecycle = Field(description="Current lifecycle.")
    relationship: StartingRelationship = Field(
        description="Independent starting relationship snapshot."
    )
    revision: int = Field(ge=1, description="Positive optimistic revision.")


class StorylineGroup(BaseModel):
    """All Storylines for one profile pair with active-slot validation.

    Attributes:
        identity_id:
            Shared identity owner.
        persona_id:
            Shared persona owner.
        storylines:
            Deterministically ordered active and archived Storylines.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity_id: UUID = Field(description="Shared identity owner.")
    persona_id: UUID = Field(description="Shared persona owner.")
    storylines: tuple[Storyline, ...] = Field(
        description="Storylines in stable repository order."
    )

    @model_validator(mode="after")
    def validate_pair_and_active_slot(self) -> Self:
        """Require shared ownership, unique identifiers, and one active Storyline.

        Returns:
            The validated immutable group.

        Raises:
            ValueError:
                If ownership differs, identifiers repeat, or two are active.
        """

        if any(
            storyline.identity_id != self.identity_id
            or storyline.persona_id != self.persona_id
            for storyline in self.storylines
        ):
            raise ValueError("Every Storyline must belong to the supplied pair")

        if len({storyline.id for storyline in self.storylines}) != len(self.storylines):
            raise ValueError("Storyline identifiers must be unique within a pair")

        if (
            sum(
                storyline.lifecycle == ContinuityLifecycle.ACTIVE
                for storyline in self.storylines
            )
            > 1
        ):
            raise ValueError("A profile pair may own at most one active Storyline")

        return self


class Scene(BaseModel):
    """One immutable-position scene snapshot with complete graph ownership.

    Attributes:
        id:
            Stable scene identifier.
        scope:
            Complete conversation and Storyline ownership.
        position:
            Positive immutable chronological position.
        details:
            Current authored metadata and fixed response style.
        setup_locked:
            Whether a first user message permanently froze setup.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(description="Stable scene identifier.")
    scope: ConversationScope = Field(description="Complete scene ownership.")
    position: int = Field(ge=1, description="Immutable chronological position.")
    details: SceneDetails = Field(
        description="Current authored metadata and fixed response behavior."
    )
    setup_locked: bool = Field(
        description="Whether the first user message froze setup."
    )


class SceneSequence(BaseModel):
    """A Storyline's scenes in immutable append-only order.

    Attributes:
        storyline:
            Owning Storyline snapshot.
        scenes:
            Consecutive scenes ordered from position one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    storyline: Storyline = Field(description="Owning Storyline snapshot.")
    scenes: tuple[Scene, ...] = Field(min_length=1, description="Ordered scenes.")

    @model_validator(mode="after")
    def validate_append_order(self) -> Self:
        """Require full ownership, unique identifiers, and consecutive positions.

        Returns:
            The validated immutable sequence.

        Raises:
            ValueError:
                If a scene is foreign, duplicated, reordered, or leaves a gap.
        """

        expected_scope = (
            self.storyline.identity_id,
            self.storyline.persona_id,
            self.storyline.id,
        )
        if any(
            (
                scene.scope.identity_id,
                scene.scope.persona_id,
                scene.scope.continuity_id,
            )
            != expected_scope
            for scene in self.scenes
        ):
            raise ValueError("Every scene must belong to the supplied Storyline")

        if len({scene.id for scene in self.scenes}) != len(self.scenes) or len(
            {scene.scope.conversation_id for scene in self.scenes}
        ) != len(self.scenes):
            raise ValueError("Scene and conversation identifiers must be unique")

        if tuple(scene.position for scene in self.scenes) != tuple(
            range(1, len(self.scenes) + 1)
        ):
            raise ValueError("Scene positions must be consecutive append order")

        if any(not scene.setup_locked for scene in self.scenes[:-1]):
            raise ValueError("Only the latest scene may have an unlocked setup")

        return self


AppendBlockReason = Literal[
    "archived_storyline",
    "not_latest_scene",
    "no_complete_exchange",
    "unmatched_input",
    "open_attempt",
]


class SceneAppendEligibility(BaseModel):
    """Persistence-neutral facts and result for appending one next scene.

    Attributes:
        storyline_id:
            Expected active Storyline.
        scene_id:
            Expected current latest scene.
        expected_storyline_revision:
            Last observed Storyline revision.
        expected_selected_leaf_id:
            Last observed selected persona leaf.
        scene_position:
            Current latest position.
        storyline_lifecycle:
            Observed Storyline lifecycle.
        is_latest_scene:
            Whether the source is still the latest scene.
        has_complete_selected_exchange:
            Whether the selected path contains a complete exchange.
        has_unmatched_input:
            Whether the selected path ends with user input.
        has_open_attempt:
            Whether generation work remains open.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    storyline_id: UUID = Field(description="Expected Storyline identifier.")
    scene_id: UUID = Field(description="Expected latest scene identifier.")
    expected_storyline_revision: int = Field(
        ge=1, description="Last observed Storyline revision."
    )
    expected_selected_leaf_id: UUID | None = Field(
        description="Last observed selected leaf."
    )
    scene_position: int = Field(ge=1, description="Observed scene position.")
    storyline_lifecycle: ContinuityLifecycle = Field(
        description="Observed Storyline lifecycle."
    )
    is_latest_scene: bool = Field(description="Whether the scene is latest.")
    has_complete_selected_exchange: bool = Field(
        description="Whether a complete selected exchange exists."
    )
    has_unmatched_input: bool = Field(
        description="Whether selected user input is unmatched."
    )
    has_open_attempt: bool = Field(description="Whether an attempt remains open.")

    @property
    def can_append(self) -> bool:
        """Derive append authorization from the observed facts.

        Returns:
            True only for an active, latest, complete, idle scene.
        """

        return self.block_reason is None

    @property
    def block_reason(self) -> AppendBlockReason | None:
        """Return the first stable reason that prevents appending.

        Returns:
            A stable reason, or None when appending is eligible.
        """

        if self.storyline_lifecycle != ContinuityLifecycle.ACTIVE:
            return "archived_storyline"
        if not self.is_latest_scene:
            return "not_latest_scene"
        if not self.has_complete_selected_exchange:
            return "no_complete_exchange"
        if self.has_unmatched_input:
            return "unmatched_input"
        if self.has_open_attempt:
            return "open_attempt"
        return None


class StorylineForkSource(BaseModel):
    """Exact guarded source point for a future reviewed Storyline fork.

    Attributes:
        scene_id:
            Source scene identifier.
        scope:
            Complete source conversation ownership.
        scene_position:
            Immutable source scene position.
        expected_storyline_revision:
            Last observed source Storyline revision.
        expected_selected_leaf_id:
            Last observed selected leaf guarding the copy.
        source_message_id:
            Exact persona response governing the requested action.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scene_id: UUID = Field(description="Source scene identifier.")
    scope: ConversationScope = Field(description="Complete source ownership.")
    scene_position: int = Field(ge=1, description="Immutable source position.")
    expected_storyline_revision: int = Field(
        ge=1, description="Last observed Storyline revision."
    )
    expected_selected_leaf_id: UUID = Field(
        description="Selected leaf guarding the source copy."
    )
    source_message_id: UUID = Field(
        description="Exact persona response governing the action."
    )


class StorylineModeAction(BaseModel):
    """Real source/latest scene facts used by fail-closed mode policy.

    Attributes:
        source:
            Exact guarded action source.
        latest_scene_id:
            Persisted latest scene identifier.
        latest_scene_position:
            Persisted latest immutable position.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: StorylineForkSource = Field(description="Exact guarded action source.")
    latest_scene_id: UUID = Field(description="Persisted latest scene identifier.")
    latest_scene_position: int = Field(
        ge=1, description="Persisted latest scene position."
    )

    @model_validator(mode="after")
    def validate_positions(self) -> Self:
        """Reject impossible source/latest scene relationships.

        Returns:
            The validated immutable action facts.

        Raises:
            ValueError:
                If the source is later than latest or equal positions differ.
        """

        if self.source.scene_position > self.latest_scene_position:
            raise ValueError("A source scene cannot be later than the latest scene")
        if (
            self.source.scene_position == self.latest_scene_position
            and self.source.scene_id != self.latest_scene_id
        ):
            raise ValueError("The latest scene identifier must match its position")
        if (
            self.source.scene_position < self.latest_scene_position
            and self.source.scene_id == self.latest_scene_id
        ):
            raise ValueError("An older source cannot use the latest scene identifier")
        return self

    @property
    def has_later_scenes(self) -> bool:
        """Derive whether the source has a later dependent scene.

        Returns:
            True when the persisted latest position follows the source.
        """

        return self.source.scene_position < self.latest_scene_position
