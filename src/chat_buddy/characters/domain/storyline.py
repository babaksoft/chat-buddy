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
from chat_buddy.characters.domain.identity import Identity
from chat_buddy.characters.domain.persona import Persona


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


class StorylineBranchSource(BaseModel):
    """Exact guarded persona point for a mode-aware Storyline branch.

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
        branch_point_message_id:
            Exact persona response where the alternate future begins.
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
    branch_point_message_id: UUID = Field(
        description="Exact persona response where the alternate future begins."
    )


class StorylineBranchLocation(BaseModel):
    """Real source/latest scene facts used by fail-closed branch policy.

    Attributes:
        source:
            Exact guarded branch source.
        latest_scene_id:
            Persisted latest scene identifier.
        latest_scene_position:
            Persisted latest immutable position.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: StorylineBranchSource = Field(description="Exact guarded branch source.")
    latest_scene_id: UUID = Field(description="Persisted latest scene identifier.")
    latest_scene_position: int = Field(
        ge=1, description="Persisted latest scene position."
    )

    @model_validator(mode="after")
    def validate_positions(self) -> Self:
        """Reject impossible source/latest scene relationships.

        Returns:
            The validated immutable branch facts.

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


ForkRecordKind = Literal[
    "identity",
    "persona",
    "continuity",
    "scene",
    "conversation",
    "message",
    "attempt",
    "summary",
    "memory",
    "memory_revision",
    "memory_evidence",
    "evolution_effect",
    "evolution_proposal",
    "evolution_event",
    "evolution_correction",
    "relationship_projection",
    "persona_adaptation_projection",
]


class StorylineForkMapping(BaseModel):
    """One explicit source-to-copy identifier mapping.

    Attributes:
        kind:
            Kind of independently owned record that was copied or retained.
        source_id:
            Identifier in the source Storyline ownership.
        target_id:
            Identifier used by the independent fork.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ForkRecordKind = Field(description="Mapped record kind.")
    source_id: UUID = Field(description="Source record identifier.")
    target_id: UUID = Field(description="Independent target identifier.")


class StorylineForkPreview(BaseModel):
    """Reviewed immutable input for one idempotent structural fork.

    Attributes:
        request_id:
            Unique confirmation identifier.
        name:
            User-authored name for the independent Storyline.
        source:
            Guarded source scene, branch point, selection, and Storyline revision.
        source_identity:
            Source identity snapshot whose authored fields define exact copying.
        source_persona:
            Source persona snapshot whose authored fields define exact copying.
        target_identity:
            Reviewed identity retained or exactly duplicated from the source.
        target_persona:
            Reviewed persona retained or exactly duplicated from the source.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    request_id: UUID = Field(description="Fork confirmation identifier.")
    name: str = Field(
        min_length=1, max_length=128, description="Authored fork Storyline name."
    )
    source: StorylineBranchSource = Field(description="Guarded source point.")
    source_identity: Identity = Field(description="Reviewed source identity.")
    source_persona: Persona = Field(description="Reviewed source persona.")
    target_identity: Identity = Field(description="Reviewed target identity.")
    target_persona: Persona = Field(description="Reviewed target persona.")

    @model_validator(mode="after")
    def validate_profiles(self) -> Self:
        """Require an exact duplicate and a distinct profile pair.

        Returns:
            The validated immutable preview.

        Raises:
            ValueError:
                If the reviewed profile pair is invalid.
        """

        if (
            self.source_identity.id == self.target_identity.id
            and self.source_persona.id == self.target_persona.id
        ):
            raise ValueError("A Storyline fork requires a distinct profile pair")

        if self.source_identity.details != self.target_identity.details:
            raise ValueError("A fork identity duplicate must be authored exactly")
        if self.source_persona.core != self.target_persona.core:
            raise ValueError("A fork persona duplicate must be authored exactly")

        if (
            self.source_identity.id != self.target_identity.id
            and self.target_identity.is_default
        ):
            raise ValueError("A duplicated identity cannot occupy the default slot")

        return self


class StorylineForkResult(BaseModel):
    """Detached result of an atomic structural Storyline fork.

    Attributes:
        storyline:
            Newly owned active Storyline.
        scenes:
            Copied scene sequence through the selected source point.
        mappings:
            Complete source-to-target identifiers for copied owned records.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    storyline: Storyline = Field(description="Independent fork Storyline.")
    scenes: tuple[Scene, ...] = Field(min_length=1, description="Copied scenes.")
    mappings: tuple[StorylineForkMapping, ...] = Field(
        min_length=1, description="Complete copied-record identifier mappings."
    )

    @model_validator(mode="after")
    def validate_ownership_and_mappings(self) -> Self:
        """Keep copied scenes and mappings unique under target ownership.

        Returns:
            The validated fork result.

        Raises:
            ValueError:
                If scene ownership, order, or identifier mappings conflict.
        """

        expected = (
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
            != expected
            for scene in self.scenes
        ):
            raise ValueError("Every copied scene must belong to the fork")

        if tuple(scene.position for scene in self.scenes) != tuple(
            range(1, len(self.scenes) + 1)
        ):
            raise ValueError("Fork scenes must retain consecutive source order")

        keys = {(mapping.kind, mapping.source_id) for mapping in self.mappings}
        targets = {(mapping.kind, mapping.target_id) for mapping in self.mappings}
        if len(keys) != len(self.mappings) or len(targets) != len(self.mappings):
            raise ValueError("Fork identifier mappings must be one-to-one per kind")

        return self
