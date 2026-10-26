"""Storyline scene adapter for shared conversation orchestration."""

from uuid import UUID

from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    BranchModeFacts,
    ContinuityMode,
    ConversationHistory,
    ConversationScope,
    ConversationTarget,
    HistoricalSceneReadOnlyError,
    LockedSceneSetupError,
    Scene,
    SceneRepository,
    Storyline,
    StorylineRepository,
)


class StorylineConversationAdapter:
    """Resolve and authorize one independently owned Storyline scene."""

    def __init__(
        self, storylines: StorylineRepository, scenes: SceneRepository
    ) -> None:
        """Bind Storyline ownership repositories.

        Args:
            storylines:
                Named continuity and lifecycle reader.
            scenes:
                Ordered scene ownership reader.
        """

        self._storylines = storylines
        self._scenes = scenes

    def inspect(
        self, target: ConversationTarget, history: ConversationHistory
    ) -> tuple[Storyline, Scene]:
        """Validate target ownership, selection shape, and setup-lock state.

        Args:
            target:
                Exact Storyline scene target.
            history:
                Selected ancestry read from that target's conversation.

        Returns:
            Owning Storyline and exact scene snapshots.

        Raises:
            ValueError:
                If target mode or selected history contradicts the scene.
            LockedSceneSetupError:
                If setup-lock state contradicts committed history.
        """

        if target.mode != ContinuityMode.STORYLINE or target.scene_id is None:
            raise ValueError("The Storyline adapter requires a Storyline target")
        if history.scope != target.scope:
            raise ValueError("Conversation history does not match its target")

        storyline, scene, _ = self._resolve(target)
        has_committed_input = bool(history.messages)
        if scene.setup_locked != has_committed_input:
            raise LockedSceneSetupError(
                "Scene setup lock does not match its committed conversation"
            )

        return storyline, scene

    def require_writable(
        self, target: ConversationTarget, history: ConversationHistory
    ) -> tuple[Storyline, Scene]:
        """Require an active latest scene before reserving conversation work.

        Args:
            target:
                Exact Storyline scene target.
            history:
                Current selected ancestry and attempts.

        Returns:
            Active owning Storyline and latest scene.

        Raises:
            ArchivedContinuityError:
                If the Storyline is archived.
            HistoricalSceneReadOnlyError:
                If the target has a later dependent scene.
        """

        storyline, scene = self.inspect(target, history)
        _, _, latest = self._resolve(target)
        if storyline.lifecycle != "active":
            raise ArchivedContinuityError("Archived Storylines are read-only")

        if scene.id != latest.id:
            raise HistoricalSceneReadOnlyError(
                "Only Branch from here can create a future from an older scene"
            )

        return storyline, scene

    def resolve(
        self,
        scope: ConversationScope,
        source_message_id: UUID,
        mode: ContinuityMode,
    ) -> BranchModeFacts:
        """Supply real latest-scene facts to the shared branch policy.

        Args:
            scope:
                Exact source conversation scope.
            source_message_id:
                Persona response governing the branch.
            mode:
                Persisted continuity mode.

        Returns:
            Exact Storyline dependent-scene facts, or absent foreign-mode facts.
        """

        if mode != ContinuityMode.STORYLINE:
            return BranchModeFacts(
                scope=scope,
                source_message_id=source_message_id,
                mode=mode,
            )

        storyline = self._storylines.get(
            scope.identity_id, scope.persona_id, scope.continuity_id
        )
        sequence = self._scenes.list(storyline)
        scene = next(
            (candidate for candidate in sequence.scenes if candidate.scope == scope),
            None,
        )
        if scene is None:
            return BranchModeFacts(
                scope=scope,
                source_message_id=source_message_id,
                mode=mode,
            )

        return BranchModeFacts(
            scope=scope,
            source_message_id=source_message_id,
            mode=mode,
            storyline_has_later_scenes=scene.position < sequence.scenes[-1].position,
        )

    def _resolve(self, target: ConversationTarget) -> tuple[Storyline, Scene, Scene]:
        """Load exact target and latest snapshots from one ordered sequence.

        Args:
            target:
                Exact Storyline scene target.

        Returns:
            Owning Storyline, target scene, and latest scene.
        """

        if target.scene_id is None:
            raise ValueError("Storyline targets require a scene identifier")

        storyline = self._storylines.get(
            target.scope.identity_id,
            target.scope.persona_id,
            target.scope.continuity_id,
        )
        scene = self._scenes.get(target.scope, target.scene_id)
        sequence = self._scenes.list(storyline)

        return sequence.storyline, scene, sequence.scenes[-1]
