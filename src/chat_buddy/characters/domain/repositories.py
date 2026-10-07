"""Persistence contracts."""

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from chat_buddy.characters.domain.branching import (
    AlternativeGroup,
    ConversationGraph,
    GraphActionRequest,
    RetryAvailability,
    SelectedPath,
)
from chat_buddy.characters.domain.continuity import (
    Continuity,
    StartContinuity,
    StartingRelationship,
)
from chat_buddy.characters.domain.conversation import (
    ConversationHistory,
    ConversationScope,
    ConversationSettings,
    GenerationAttempt,
    Message,
    SubmittedInput,
)
from chat_buddy.characters.domain.identity import Identity, IdentityDetails
from chat_buddy.characters.domain.llm import EffectiveGeneration
from chat_buddy.characters.domain.persona import Persona, PersonaCore
from chat_buddy.characters.domain.summary import SummaryRevision


class IdentityRepository(Protocol):
    """Manage identity snapshots while exposing domain models only."""

    def create(self, details: IdentityDetails) -> Identity:
        """Persist a new editable identity.

        Args:
            details:
                Authored fields to persist.

        Returns:
            The newly identified snapshot.
        """

        ...

    def ensure_default(self) -> Identity:
        """Return or atomically create the sole default You identity.

        Returns:
            The existing or newly created default identity.
        """

        ...

    def get(self, identity_id: UUID) -> Identity:
        """Read an identity or raise IdentityNotFoundError.

        Args:
            identity_id:
                Stable identity identifier.

        Returns:
            The persisted snapshot.

        Raises:
            IdentityNotFoundError:
                If the requested identity does not exist.
        """

        ...

    def list(self) -> list[Identity]:
        """Read identities ordered by default-first, then by name and identifier.

        Returns:
            Deterministically ordered snapshots.
        """

        ...

    def replace(
        self, identity_id: UUID, details: IdentityDetails, expected_revision: int
    ) -> Identity:
        """Atomically replace an editable identity at the expected revision.

        Args:
            identity_id:
                Stable identity identifier.
            details:
                Replacement authored fields.
            expected_revision:
                Last observed revision, rejecting stale writes.

        Returns:
            The updated snapshot.

        Raises:
            IdentityNotFoundError:
                If no such identity exists.
            FrozenIdentityError:
                If the persisted identity is frozen.
            StaleIdentityError:
                If a competing edit changed the revision.
        """

        ...


class PersonaRepository(Protocol):
    """Manage persona snapshots while exposing domain models only."""

    def create(self, core: PersonaCore) -> Persona:
        """Persist a new editable persona.

        Args:
            core:
                Authored fields to persist.

        Returns:
            The newly identified snapshot.
        """

        ...

    def get(self, persona_id: UUID) -> Persona:
        """Read a persona or raise PersonaNotFoundError.

        Args:
            persona_id:
                Stable persona identifier.

        Returns:
            The persisted snapshot.

        Raises:
            PersonaNotFoundError:
                If the requested persona does not exist.
        """

        ...

    def list(self) -> list[Persona]:
        """Read personas ordered by name and identifier.

        Returns:
            Deterministically ordered snapshots.
        """

        ...

    def replace(
        self, persona_id: UUID, core: PersonaCore, expected_revision: int
    ) -> Persona:
        """Atomically replace an editable persona at the expected revision.

        Args:
            persona_id:
                Stable persona identifier.
            core:
                Replacement authored fields.
            expected_revision:
                Last observed revision, rejecting stale writes.

        Returns:
            The updated snapshot.

        Raises:
            PersonaNotFoundError:
                If no such persona exists.
            FrozenPersonaError:
                If the persisted persona is frozen.
            StalePersonaError:
                If a competing edit changed the revision.
        """

        ...


class ContinuityRepository(Protocol):
    """Manage continuity lifecycle and ownership while exposing domain objects only."""

    def start(
        self, request: StartContinuity, relationship: StartingRelationship
    ) -> Continuity:
        """Atomically verify, freeze, and persist an idempotent confirmed start.

        Args:
            request:
                Complete reviewed confirmation.
            relationship:
                Resolved starting state and provenance.

        Returns:
            New continuity or the original identical confirmation result.
        """

        ...

    def find_confirmation(self, request: StartContinuity) -> Continuity | None:
        """Read an identical persisted confirmation before preflight checks.

        Args:
            request:
                Complete confirmed request.

        Returns:
            Original continuity, or None for a new confirmation.

        Raises:
            ConfirmationConflictError:
                If submitted data differs from the persisted confirmation.
        """

        ...

    def find_active(self, identity_id: UUID, persona_id: UUID) -> Continuity | None:
        """Find the pair's active Ongoing for application preflight checks.

        Args:
            identity_id:
                Selected identity owner.
            persona_id:
                Selected persona owner.

        Returns:
            Active Ongoing snapshot, or None if the pair has no active Ongoing.
        """

        ...

    def get(
        self, identity_id: UUID, persona_id: UUID, continuity_id: UUID
    ) -> Continuity:
        """Read within explicit identity/persona ownership, including archives.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            continuity_id:
                Continuity to inspect.

        Returns:
            The owned continuity snapshot.
        """

        ...

    def list(self) -> list[Continuity]:
        """Read snapshots ordered by identity, persona, and continuity UUID.

        Returns:
            All independently owned lifecycle snapshots.
        """

        ...

    def archive(
        self, identity_id: UUID, persona_id: UUID, continuity_id: UUID
    ) -> Continuity:
        """Lock and permanently archive a continuity within its ownership scope.

        Args:
            identity_id:
                Expected identity owner.
            persona_id:
                Expected persona owner.
            continuity_id:
                Continuity to archive.

        Returns:
            The archived snapshot, including repeated archive requests.
        """

        ...


class ConversationGraphRepository(Protocol):
    """Keep selected-path reads separate from complete graph inspection."""

    def selected_path(self, scope: ConversationScope) -> SelectedPath:
        """Read only the selected root-to-leaf ancestry.

        Args:
            scope:
                Complete required ownership.

        Returns:
            Detached selected path, excluding every sibling.
        """

        ...

    def graph(self, scope: ConversationScope) -> ConversationGraph:
        """Inspect every node independently from ordinary history reads.

        Args:
            scope:
                Complete required ownership.

        Returns:
            Detached graph with deterministic sibling ordering.
        """

        ...

    def alternatives(
        self, scope: ConversationScope, user_message_id: UUID
    ) -> AlternativeGroup:
        """Read completed persona siblings for one owned user node.

        Args:
            scope:
                Complete required ownership.
            user_message_id:
                Exact shared user parent.

        Returns:
            Deterministically ordered alternatives.
        """

        ...

    def select_leaf(
        self,
        scope: ConversationScope,
        message_id: UUID,
        expected_selected_leaf_id: UUID | None,
    ) -> SelectedPath:
        """Select an exact persona node under a compare-and-swap guard.

        Args:
            scope:
                Complete required ownership.
            message_id:
                Exact persona node to select.
            expected_selected_leaf_id:
                Last selected leaf observed by the caller.

        Returns:
            Newly selected ancestry.
        """

        ...

    def apply_action(self, request: GraphActionRequest) -> SelectedPath:
        """Apply one validated graph action under the selection lock.

        Args:
            request:
                Fully owned action target and compare-and-swap guard.

        Returns:
            Newly selected ancestry.
        """

        ...


class ConversationRepository(Protocol):
    """Serialize message and attempt writes with continuity archival."""

    def history(self, scope: ConversationScope) -> ConversationHistory:
        """Read committed history and attempt provenance.

        Args:
            scope:
                Complete required ownership.

        Returns:
            Detached domain snapshot.
        """

        ...

    def configure(
        self, scope: ConversationScope, settings: ConversationSettings
    ) -> None:
        """Save next-attempt defaults on a writable conversation.

        Args:
            scope:
                Complete required ownership.
            settings:
                Validated requested selection.
        """

        ...

    def begin(
        self,
        scope: ConversationScope,
        generation: EffectiveGeneration,
        settings: ConversationSettings,
        expected_selected_leaf_id: UUID | None,
        submitted: SubmittedInput | None,
    ) -> GenerationAttempt:
        """Atomically reserve an attempt and optionally append its user message.

        Args:
            scope:
                Complete required ownership.
            generation:
                Immutable effective response configuration.
            settings:
                Current requested selection to persist.
            expected_selected_leaf_id:
                Last selected leaf observed during prompt preflight.
            submitted:
                New input, or None to continue the existing unmatched tail.

        Returns:
            Detached domain snapshot.
        """

        ...

    def retry_availability(
        self, scope: ConversationScope, persona_message_id: UUID
    ) -> RetryAvailability:
        """Count durable completed alternatives for the selected response.

        Args:
            scope:
                Complete required ownership.
            persona_message_id:
                Selected final persona response.

        Returns:
            Successful retry accounting for the response's user parent.
        """

        ...

    def begin_retry(
        self,
        scope: ConversationScope,
        generation: EffectiveGeneration,
        settings: ConversationSettings,
        expected_selected_leaf_id: UUID,
    ) -> GenerationAttempt:
        """Reserve a bounded retry for the selected completed response.

        Args:
            scope:
                Complete required ownership.
            generation:
                Immutable effective response configuration.
            settings:
                Current requested selection to persist.
            expected_selected_leaf_id:
                Selected final persona response observed during preflight.

        Returns:
            Detached pending retry attempt.
        """

        ...

    def claim(self, scope: ConversationScope, attempt_id: UUID) -> GenerationAttempt:
        """Atomically transition a pending attempt to streaming.

        Args:
            scope:
                Complete required ownership.
            attempt_id:
                Pending attempt identifier.

        Returns:
            Detached domain snapshot.
        """

        ...

    def append(self, scope: ConversationScope, attempt_id: UUID, chunk: str) -> None:
        """Persist progress and refresh its heartbeat.

        Args:
            scope:
                Complete required ownership.
            attempt_id:
                Streaming attempt identifier.
            chunk:
                New output text.
        """

        ...

    def complete(self, scope: ConversationScope, attempt_id: UUID) -> Message:
        """Atomically append a persona message and complete its attempt.

        Args:
            scope:
                Complete required ownership.
            attempt_id:
                Streaming attempt identifier.

        Returns:
            Detached domain snapshot.
        """

        ...

    def stop(
        self,
        scope: ConversationScope,
        attempt_id: UUID,
        status: Literal["failed", "interrupted"],
    ) -> None:
        """Terminate an open attempt.

        Args:
            scope:
                Complete required ownership.
            attempt_id:
                Attempt to terminate.
            status:
                Terminal failure or interruption status.
        """

        ...

    def reconcile(
        self, scope: ConversationScope, inactive_before: datetime
    ) -> ConversationHistory:
        """Interrupt expired attempts while fencing their late output.

        Args:
            scope:
                Complete required ownership.
            inactive_before:
                Only heartbeats at or before this UTC cutoff are abandoned.

        Returns:
            Detached domain snapshot.
        """

        ...


class SummaryRepository(Protocol):
    """Persist immutable rolling-summary revisions."""

    def get_current(
        self, scope: ConversationScope, path_leaf_id: UUID | None = None
    ) -> SummaryRevision | None:
        """Load the deepest compatible revision for the selected ancestry.

        Args:
            scope:
                Complete required ownership.
            path_leaf_id:
                Exact ancestry leaf, or the selected leaf when absent.

        Returns:
            Current compatible revision when one exists.
        """

        ...

    def append(
        self,
        replacement: SummaryRevision,
        expected_revision: int | None,
        expected_checkpoint_id: UUID | None,
    ) -> SummaryRevision:
        """Atomically append a successor to the compatible lineage.

        Args:
            replacement:
                Proposed active successor.
            expected_revision:
                Previously observed active revision, absent on first creation.
            expected_checkpoint_id:
                Previously observed checkpoint, absent on first creation.

        Returns:
            Persisted active revision.
        """

        ...
