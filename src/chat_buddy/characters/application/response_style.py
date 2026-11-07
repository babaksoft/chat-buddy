"""Explicit defaults and deterministic rendering for response presentation."""

from uuid import UUID

from chat_buddy.characters.application.diagnostics import (
    NoOpCharactersDiagnosticObserver,
)
from chat_buddy.characters.domain import (
    CharactersDiagnostic,
    CharactersDiagnosticName,
    CharactersDiagnosticObserver,
    ContinuityMode,
    NarrativePlacement,
    ResponseLength,
    ResponseStyle,
    ResponseStyleRepository,
    ResponseStyleSettings,
    SceneDescriptionLevel,
    StyleUpdateResult,
    VersionedResponseStyleSettings,
)

RESPONSE_STYLE_RENDERER_NAME = "characters.response_style"
RESPONSE_STYLE_RENDERER_VERSION = "1.0.0"

_DEFAULTS = {
    ContinuityMode.ONGOING: ResponseStyleSettings(
        scene_description=SceneDescriptionLevel.NONE,
        response_length=ResponseLength.BALANCED,
        narrative_placement=NarrativePlacement.INTERLEAVED,
    ),
    ContinuityMode.STORYLINE: ResponseStyleSettings(
        scene_description=SceneDescriptionLevel.BALANCED,
        response_length=ResponseLength.BALANCED,
        narrative_placement=NarrativePlacement.INTERLEAVED,
    ),
    ContinuityMode.TIMELINE: ResponseStyleSettings(
        scene_description=SceneDescriptionLevel.BALANCED,
        response_length=ResponseLength.BALANCED,
        narrative_placement=NarrativePlacement.INTERLEAVED,
    ),
}

_SCENE_DESCRIPTION_INSTRUCTIONS = {
    SceneDescriptionLevel.NONE: "Do not add scene description or narrated action.",
    SceneDescriptionLevel.LIGHT: (
        "Use light scene description: include only brief environmental, action, "
        "or non-verbal details when they help the response."
    ),
    SceneDescriptionLevel.BALANCED: (
        "Use balanced scene description: include relevant environmental, action, "
        "and non-verbal details without letting them dominate the response."
    ),
    SceneDescriptionLevel.RICH: (
        "Use rich scene description: give substantial environmental, action, and "
        "non-verbal detail while preserving conversational clarity."
    ),
}

_RESPONSE_LENGTH_INSTRUCTIONS = {
    ResponseLength.CONCISE: "Keep the response concise and focused.",
    ResponseLength.BALANCED: "Use a balanced response length with enough useful detail.",
    ResponseLength.EXPANSIVE: (
        "Use an expansive response when context supports it, with developed detail "
        "and progression."
    ),
}

_NARRATIVE_PLACEMENT_INSTRUCTIONS = {
    NarrativePlacement.BEFORE_DIALOGUE: (
        "Place scene description before ordinary prose or dialogue."
    ),
    NarrativePlacement.INTERLEAVED: (
        "Interleave scene description naturally with ordinary prose or dialogue."
    ),
    NarrativePlacement.AFTER_DIALOGUE: (
        "Place scene description after ordinary prose or dialogue."
    ),
}

_MARKDOWN_CONVENTION = (
    "Markdown convention:\n"
    "- When scene description is enabled, write persona scene description and "
    "action in simple italics.\n"
    "- Keep ordinary prose and dialogue plain; use bold only sparingly for natural "
    "emphasis.\n"
    "- Choose single quotes, double quotes, or both according to language and "
    "context.\n"
    "- For an embedded exchange, use any clear ordinary Markdown structure, such "
    "as speaker-labelled lines, lists, or blockquotes.\n"
    "- Do not use raw HTML."
)


def default_response_style(mode: ContinuityMode) -> ResponseStyleSettings:
    """Return the explicit immutable default for a continuity mode.

    Args:
        mode:
            Continuity mode whose initial settings are required.

    Returns:
        Mode-specific default settings.
    """

    return _DEFAULTS[mode]


class ResponseStyleRenderer:
    """Render complete settings into a stable, versioned prompt snapshot."""

    def render(self, current: VersionedResponseStyleSettings) -> ResponseStyle:
        """Render controls in fixed order followed by the Markdown convention.

        Args:
            current:
                Complete settings and their committed source revision.

        Returns:
            Exact immutable effective style snapshot.
        """

        settings = current.settings
        instruction = "\n".join(
            (
                "Response presentation:",
                "Scene description: "
                + _SCENE_DESCRIPTION_INSTRUCTIONS[settings.scene_description],
                "Response length: "
                + _RESPONSE_LENGTH_INSTRUCTIONS[settings.response_length],
                "Narrative placement: "
                + _NARRATIVE_PLACEMENT_INSTRUCTIONS[settings.narrative_placement],
                _MARKDOWN_CONVENTION,
            )
        )

        return ResponseStyle(
            name=RESPONSE_STYLE_RENDERER_NAME,
            version=RESPONSE_STYLE_RENDERER_VERSION,
            scene_description=settings.scene_description,
            response_length=settings.response_length,
            narrative_placement=settings.narrative_placement,
            source_revision=current.revision,
            instruction=instruction,
        )


class ResponseStyleService:
    """Resolve and update continuity-owned response presentation."""

    def __init__(
        self,
        repository: ResponseStyleRepository,
        renderer: ResponseStyleRenderer | None = None,
        diagnostics: CharactersDiagnosticObserver | None = None,
    ) -> None:
        """Initialize response-style operations.

        Args:
            repository:
                Continuity-owned style persistence.
            renderer:
                Optional deterministic renderer override.
            diagnostics:
                Optional privacy-safe structured diagnostic sink.
        """

        self._repository = repository
        self._renderer = renderer or ResponseStyleRenderer()
        self._diagnostics = diagnostics or NoOpCharactersDiagnosticObserver()

    def get(self, continuity_id: UUID) -> VersionedResponseStyleSettings:
        """Load the current requested controls and revision.

        Args:
            continuity_id:
                Owning Characters continuity.

        Returns:
            Current committed settings.
        """

        return self._repository.get(continuity_id)

    def resolve(self, continuity_id: UUID) -> ResponseStyle:
        """Render the current settings into an effective snapshot.

        Args:
            continuity_id:
                Owning Characters continuity.

        Returns:
            Complete versioned response-style instruction.
        """

        return self._renderer.render(self.get(continuity_id))

    def update(
        self,
        continuity_id: UUID,
        settings: ResponseStyleSettings,
        expected_revision: int,
    ) -> StyleUpdateResult:
        """Atomically replace all controls under an optimistic revision.

        Args:
            continuity_id:
                Owning Characters continuity.
            settings:
                Complete replacement controls.
            expected_revision:
                Last observed positive style revision.

        Returns:
            Explicit updated, idempotent, stale, or archived outcome.
        """

        result = self._repository.update(continuity_id, settings, expected_revision)
        self._diagnostics.emit(
            CharactersDiagnostic(
                name=CharactersDiagnosticName.RESPONSE_STYLE_REVISION,
                continuity_id=continuity_id,
                policy=RESPONSE_STYLE_RENDERER_NAME,
                version=RESPONSE_STYLE_RENDERER_VERSION,
                terminal_reason=result.status.value,
            )
        )
        return result
