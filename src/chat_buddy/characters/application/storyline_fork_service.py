"""Reviewed structural Storyline fork orchestration."""

from uuid import UUID

from chat_buddy.characters.application.branch_policy import decide_branch_mode
from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    ConversationGraphRepository,
    ConversationRepository,
    ConversationTarget,
    IdentityRepository,
    MessageNode,
    PersonaRepository,
    SceneRepository,
    StaleStorylineError,
    StorylineBranchLocation,
    StorylineBranchSource,
    StorylineForkConflictError,
    StorylineForkPreview,
    StorylineForkRepository,
    StorylineForkResult,
    StorylineRepository,
)


class StorylineForkService:
    """Prepare and commit exact reviewed forks."""

    def __init__(
        self,
        storylines: StorylineRepository,
        scenes: SceneRepository,
        conversations: ConversationRepository,
        graphs: ConversationGraphRepository,
        identities: IdentityRepository,
        personas: PersonaRepository,
        forks: StorylineForkRepository,
    ) -> None:
        """Bind source readers and the atomic fork writer.

        Args:
            storylines:
                Storyline ownership and lifecycle reader.
            scenes:
                Ordered scene ownership reader.
            conversations:
                Attempt and selected-history reader.
            graphs:
                Complete immutable graph reader.
            identities:
                Reviewed identity reader.
            personas:
                Reviewed persona reader.
            forks:
                Atomic structural fork repository.
        """

        self._storylines = storylines
        self._scenes = scenes
        self._conversations = conversations
        self._graphs = graphs
        self._identities = identities
        self._personas = personas
        self._forks = forks

    def preview(
        self,
        request_id: UUID,
        name: str,
        target: ConversationTarget,
        branch_point_message_id: UUID,
        expected_selected_leaf_id: UUID,
        expected_storyline_revision: int,
        target_identity_id: UUID,
        target_persona_id: UUID,
    ) -> StorylineForkPreview:
        """Validate and return the complete immutable confirmation snapshot.

        Args:
            request_id:
                Unique confirmation identifier.
            name:
                User-authored name for the new Storyline.
            target:
                Exact older source scene ownership.
            branch_point_message_id:
                Exact persona node where the alternate future begins.
            expected_selected_leaf_id:
                Selected source leaf observed by the caller.
            expected_storyline_revision:
                Storyline revision observed by the caller.
            target_identity_id:
                Retained or exactly duplicated identity.
            target_persona_id:
                Retained or exactly duplicated persona.

        Returns:
            Reviewed source and target snapshot ready for confirmation.

        Raises:
            StorylineForkConflictError:
                If source state, branch point, or target ownership is invalid.
        """

        if target.scene_id is None or target.mode != "storyline":
            raise StorylineForkConflictError("A fork requires a Storyline scene")

        storyline = self._storylines.get(
            target.scope.identity_id,
            target.scope.persona_id,
            target.scope.continuity_id,
        )
        if storyline.lifecycle != "active":
            raise ArchivedContinuityError("Archived Storylines cannot be forked")
        if storyline.revision != expected_storyline_revision:
            raise StaleStorylineError("Storyline changed before fork review")

        scene = self._scenes.get(target.scope, target.scene_id)
        sequence = self._scenes.list(storyline)
        latest = sequence.scenes[-1]
        decision = decide_branch_mode(
            StorylineBranchLocation(
                source=StorylineBranchSource(
                    scene_id=scene.id,
                    scope=scene.scope,
                    scene_position=scene.position,
                    expected_storyline_revision=storyline.revision,
                    expected_selected_leaf_id=expected_selected_leaf_id,
                    branch_point_message_id=branch_point_message_id,
                ),
                latest_scene_id=latest.id,
                latest_scene_position=latest.position,
            )
        )
        if decision.disposition != "fork_required":
            raise StorylineForkConflictError(
                "The latest Storyline scene must change in place"
            )

        history = self._conversations.history(scene.scope)
        if history.messages and history.messages[-1].id != expected_selected_leaf_id:
            raise StorylineForkConflictError("Source selection changed before review")
        if not history.messages:
            raise StorylineForkConflictError("An empty scene cannot be forked")
        if any(
            attempt.status in {"pending", "streaming"} for attempt in history.attempts
        ):
            raise StorylineForkConflictError("An open source attempt prevents a fork")

        graph = self._graphs.graph(scene.scope)
        self._validate_branch_point(
            graph.nodes,
            branch_point_message_id,
        )

        source_identity = self._identities.get(storyline.identity_id)
        source_persona = self._personas.get(storyline.persona_id)
        target_identity = self._identities.get(target_identity_id)
        target_persona = self._personas.get(target_persona_id)
        target_group = self._storylines.list_for_pair(
            target_identity.id, target_persona.id
        )
        if target_group.storylines:
            raise StorylineForkConflictError(
                "The target profile pair already owns a Storyline"
            )

        try:
            return StorylineForkPreview(
                request_id=request_id,
                name=name,
                source=StorylineBranchSource(
                    scene_id=scene.id,
                    scope=scene.scope,
                    scene_position=scene.position,
                    expected_storyline_revision=storyline.revision,
                    expected_selected_leaf_id=expected_selected_leaf_id,
                    branch_point_message_id=branch_point_message_id,
                ),
                source_identity=source_identity,
                source_persona=source_persona,
                target_identity=target_identity,
                target_persona=target_persona,
            )
        except ValueError as error:
            raise StorylineForkConflictError(str(error)) from error

    def confirm(self, preview: StorylineForkPreview) -> StorylineForkResult:
        """Commit a reviewed fork idempotently.

        Args:
            preview:
                Exact immutable preview previously returned to the caller.

        Returns:
            New or idempotently existing fork result.
        """

        existing = self._forks.find_confirmation(preview)
        return existing if existing is not None else self._forks.fork(preview)

    @staticmethod
    def _validate_branch_point(
        nodes: tuple[MessageNode, ...],
        branch_point_message_id: UUID,
    ) -> None:
        """Require an exact owned persona branch point before review.

        Args:
            nodes:
                Complete source graph nodes.
            branch_point_message_id:
                Exact persona branch point.

        Raises:
            StorylineForkConflictError:
                If the branch point contradicts graph state.
        """

        target = next(
            (node for node in nodes if node.id == branch_point_message_id), None
        )
        if target is None or target.role != "persona":
            raise StorylineForkConflictError(
                "A fork requires an owned persona branch point"
            )
