"""Storyline lifecycle orchestration without persistence details."""

from uuid import UUID

from chat_buddy.characters.application.starting_relationship import (
    resolve_starting_relationship,
)
from chat_buddy.characters.domain import (
    ActiveStorylineError,
    ConversationRepository,
    ConversationScope,
    Scene,
    SceneAppendEligibility,
    SceneDetails,
    SceneRepository,
    SceneSequence,
    StartAvailability,
    StartStoryline,
    Storyline,
    StorylineGroup,
    StorylineRepository,
)


class StorylineService:
    """Start, inspect, edit, extend, and archive Storylines."""

    def __init__(
        self,
        storylines: StorylineRepository,
        scenes: SceneRepository,
        conversations: ConversationRepository,
    ) -> None:
        """Initialize Storyline lifecycle operations.

        Args:
            storylines:
                Atomic Storyline ownership repository.
            scenes:
                Ordered scene repository.
            conversations:
                Conversation reader used to derive append eligibility.
        """

        self._storylines = storylines
        self._scenes = scenes
        self._conversations = conversations

    def start(self, request: StartStoryline) -> tuple[Storyline, Scene]:
        """Commit a reviewed Storyline and its initial scene idempotently.

        Args:
            request:
                Complete reviewed profiles, relationship, and authored fields.

        Returns:
            The new or idempotently existing Storyline and initial scene.

        Raises:
            ActiveStorylineError:
                If the pair already owns an active Storyline.
            ConfirmationConflictError:
                If the confirmation identifier was reused with changed inputs.
            StaleIdentityError:
                If the reviewed identity revision changed.
            StalePersonaError:
                If the reviewed persona revision changed.
        """

        confirmed = self._storylines.find_confirmation(request)
        if confirmed is not None:
            return confirmed

        if self._storylines.find_active(request.identity_id, request.persona_id):
            confirmed = self._storylines.find_confirmation(request)
            if confirmed is not None:
                return confirmed

            raise ActiveStorylineError(
                "Archive the active Storyline before starting a replacement"
            )

        return self._storylines.start(
            request, resolve_starting_relationship(request.relationship)
        )

    def start_availability(
        self, identity_id: UUID, persona_id: UUID
    ) -> StartAvailability:
        """Describe whether the pair has a free active Storyline slot.

        Args:
            identity_id:
                Selected identity owner.
            persona_id:
                Selected persona owner.

        Returns:
            Mode-specific availability and an optional blocking reason.
        """

        if self._storylines.find_active(identity_id, persona_id) is not None:
            return StartAvailability(
                can_start=False,
                reason="Archive the active Storyline before starting another.",
            )

        return StartAvailability(can_start=True)

    def list_grouped(self) -> tuple[StorylineGroup, ...]:
        """List Storylines grouped deterministically by their profile pair.

        Returns:
            Stable identity/persona groups with active and archived Storylines.
        """

        return self._storylines.list()

    def list_for_pair(self, identity_id: UUID, persona_id: UUID) -> StorylineGroup:
        """List active and archived Storylines for one profile pair.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.

        Returns:
            Deterministically ordered Storylines for the pair.
        """

        return self._storylines.list_for_pair(identity_id, persona_id)

    def resume_latest(
        self, identity_id: UUID, persona_id: UUID, storyline_id: UUID
    ) -> tuple[Storyline, Scene]:
        """Load a Storyline and its latest scene for active or archived reading.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            storyline_id:
                Storyline to resume or inspect.

        Returns:
            Current Storyline snapshot and its chronologically latest scene.
        """

        storyline = self._storylines.get(identity_id, persona_id, storyline_id)
        sequence = self._scenes.list(storyline)
        return sequence.storyline, sequence.scenes[-1]

    def resume(
        self, identity_id: UUID, persona_id: UUID, storyline_id: UUID
    ) -> SceneSequence:
        """Load a Storyline and every scene in chronological order.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            storyline_id:
                Storyline to resume or inspect.

        Returns:
            Current Storyline and its complete ordered scene sequence.
        """

        storyline = self._storylines.get(identity_id, persona_id, storyline_id)
        return self._scenes.list(storyline)

    def append_eligibility(
        self, identity_id: UUID, persona_id: UUID, storyline_id: UUID
    ) -> SceneAppendEligibility:
        """Derive guarded next-scene eligibility from the current latest scene.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            storyline_id:
                Storyline whose latest scene is being considered.

        Returns:
            Complete observed facts and optimistic append guards.
        """

        storyline = self._storylines.get(identity_id, persona_id, storyline_id)
        sequence = self._scenes.list(storyline)
        latest = sequence.scenes[-1]

        history = self._conversations.history(latest.scope)
        leaf = history.messages[-1] if history.messages else None

        return SceneAppendEligibility(
            storyline_id=sequence.storyline.id,
            scene_id=latest.id,
            expected_storyline_revision=sequence.storyline.revision,
            expected_selected_leaf_id=None if leaf is None else leaf.id,
            scene_position=latest.position,
            storyline_lifecycle=sequence.storyline.lifecycle,
            is_latest_scene=True,
            has_complete_selected_exchange=leaf is not None and leaf.role == "persona",
            has_unmatched_input=leaf is not None and leaf.role == "user",
            has_open_attempt=any(
                attempt.status in {"pending", "streaming"}
                for attempt in history.attempts
            ),
        )

    def append_next(
        self, details: SceneDetails, eligibility: SceneAppendEligibility
    ) -> SceneSequence:
        """Append one next scene under previously observed eligibility guards.

        Args:
            details:
                Authored next-scene metadata and fixed response style.
            eligibility:
                Current eligibility returned by :meth:`append_eligibility`.

        Returns:
            Updated complete scene sequence.
        """

        return self._scenes.append_next(details, eligibility)

    def rename(
        self,
        identity_id: UUID,
        persona_id: UUID,
        storyline_id: UUID,
        name: str,
        expected_revision: int,
    ) -> Storyline:
        """Rename an active Storyline under an optimistic revision guard.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            storyline_id:
                Storyline to rename.
            name:
                Replacement authored name.
            expected_revision:
                Last observed Storyline revision.

        Returns:
            Renamed Storyline snapshot.
        """

        return self._storylines.rename(
            identity_id, persona_id, storyline_id, name, expected_revision
        )

    def rename_scene(
        self,
        scope: ConversationScope,
        scene_id: UUID,
        title: str,
        expected_storyline_revision: int,
    ) -> Scene:
        """Rename scene presentation metadata under ownership guards.

        Args:
            scope:
                Complete scene ownership.
            scene_id:
                Scene to rename.
            title:
                Replacement presentation title.
            expected_storyline_revision:
                Last observed Storyline revision.

        Returns:
            Updated scene snapshot.
        """

        return self._scenes.rename(scope, scene_id, title, expected_storyline_revision)

    def replace_scene_setup(
        self,
        scope: ConversationScope,
        scene_id: UUID,
        setup: str,
        expected_storyline_revision: int,
    ) -> Scene:
        """Edit a latest scene setup before its first committed user message.

        Args:
            scope:
                Complete scene ownership.
            scene_id:
                Scene whose setup is changing.
            setup:
                Replacement authored setup.
            expected_storyline_revision:
                Last observed Storyline revision.

        Returns:
            Updated unlocked scene snapshot.
        """

        return self._scenes.replace_setup(
            scope, scene_id, setup, expected_storyline_revision
        )

    def archive(
        self,
        identity_id: UUID,
        persona_id: UUID,
        storyline_id: UUID,
        expected_revision: int,
    ) -> Storyline:
        """Permanently archive a Storyline without unfreezing its profiles.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            storyline_id:
                Storyline to archive.
            expected_revision:
                Last observed Storyline revision.

        Returns:
            Archived snapshot, including an identical repeated request.
        """

        return self._storylines.archive(
            identity_id, persona_id, storyline_id, expected_revision
        )
