"""Tests for response-style defaults and deterministic rendering."""

from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from chat_buddy.characters.application import (
    RESPONSE_STYLE_RENDERER_NAME,
    RESPONSE_STYLE_RENDERER_VERSION,
    ResponseStyleRenderer,
    ResponseStyleService,
    default_response_style,
)
from chat_buddy.characters.domain import (
    CharactersDiagnosticName,
    ContinuityMode,
    NarrativePlacement,
    ResponseLength,
    ResponseStyleSettings,
    SceneDescriptionLevel,
    StyleUpdateResult,
    StyleUpdateStatus,
    VersionedResponseStyleSettings,
)


class FakeStyleRepository:
    """Store one in-memory style snapshot for application-service tests."""

    def __init__(self, current: VersionedResponseStyleSettings) -> None:
        """Capture initial settings.

        Args:
            current:
                Initial committed settings.
        """

        self.current = current

    def get(self, continuity_id: UUID) -> VersionedResponseStyleSettings:
        """Return the current settings.

        Args:
            continuity_id:
                Ignored test continuity identifier.

        Returns:
            Current in-memory settings.
        """

        return self.current

    def update(
        self,
        continuity_id: UUID,
        settings: ResponseStyleSettings,
        expected_revision: int,
    ) -> StyleUpdateResult:
        """Replace settings when the expected revision matches.

        Args:
            continuity_id:
                Ignored test continuity identifier.
            settings:
                Complete replacement settings.
            expected_revision:
                Last observed revision.

        Returns:
            Updated or stale test result.
        """

        if expected_revision != self.current.revision:
            return StyleUpdateResult(
                status=StyleUpdateStatus.STALE_REVISION, style=self.current
            )
        self.current = VersionedResponseStyleSettings(
            settings=settings, revision=self.current.revision + 1
        )
        return StyleUpdateResult(status=StyleUpdateStatus.UPDATED, style=self.current)


def test_style_update_emits_only_revision_diagnostics() -> None:
    """Describe a style revision without rendered instructions or authored text."""

    continuity_id = uuid4()
    current = VersionedResponseStyleSettings(
        settings=default_response_style(ContinuityMode.TIMELINE), revision=1
    )
    diagnostics = Mock()
    service = ResponseStyleService(
        FakeStyleRepository(current), diagnostics=diagnostics
    )

    result = service.update(continuity_id, current.settings, 1)

    assert result.status == StyleUpdateStatus.UPDATED
    diagnostic = diagnostics.emit.call_args.args[0]
    assert diagnostic.name == CharactersDiagnosticName.RESPONSE_STYLE_REVISION
    assert diagnostic.continuity_id == continuity_id
    assert diagnostic.terminal_reason == "updated"
    assert "instruction" not in diagnostic.model_dump()


@pytest.mark.parametrize(
    ("mode", "scene_description"),
    [
        (ContinuityMode.ONGOING, SceneDescriptionLevel.NONE),
        (ContinuityMode.STORYLINE, SceneDescriptionLevel.BALANCED),
        (ContinuityMode.TIMELINE, SceneDescriptionLevel.BALANCED),
    ],
)
def test_defaults_are_explicit_for_every_mode(
    mode: ContinuityMode, scene_description: SceneDescriptionLevel
) -> None:
    """Resolve the accepted complete default for each continuity mode."""

    settings = default_response_style(mode)

    assert settings.scene_description == scene_description
    assert settings.response_length == ResponseLength.BALANCED
    assert settings.narrative_placement == NarrativePlacement.INTERLEAVED


@pytest.mark.parametrize("scene_description", list(SceneDescriptionLevel))
@pytest.mark.parametrize("response_length", list(ResponseLength))
@pytest.mark.parametrize("narrative_placement", list(NarrativePlacement))
def test_renderer_covers_every_control_value(
    scene_description: SceneDescriptionLevel,
    response_length: ResponseLength,
    narrative_placement: NarrativePlacement,
) -> None:
    """Render every supported combination into a bounded exact snapshot."""

    settings = ResponseStyleSettings(
        scene_description=scene_description,
        response_length=response_length,
        narrative_placement=narrative_placement,
    )
    snapshot = ResponseStyleRenderer().render(
        VersionedResponseStyleSettings(settings=settings, revision=7)
    )

    assert snapshot.name == RESPONSE_STYLE_RENDERER_NAME
    assert snapshot.version == RESPONSE_STYLE_RENDERER_VERSION
    assert snapshot.scene_description == scene_description
    assert snapshot.response_length == response_length
    assert snapshot.narrative_placement == narrative_placement
    assert snapshot.source_revision == 7
    assert len(snapshot.instruction) <= 4096


def test_renderer_order_and_markdown_convention_are_stable() -> None:
    """Emit the three controls in table order before fixed Markdown rules."""

    snapshot = ResponseStyleRenderer().render(
        VersionedResponseStyleSettings(
            settings=ResponseStyleSettings(
                scene_description=SceneDescriptionLevel.NONE,
                response_length=ResponseLength.CONCISE,
                narrative_placement=NarrativePlacement.AFTER_DIALOGUE,
            ),
            revision=2,
        )
    )

    instruction = snapshot.instruction
    assert instruction.index("Scene description:") < instruction.index(
        "Response length:"
    )
    assert instruction.index("Response length:") < instruction.index(
        "Narrative placement:"
    )
    assert instruction.index("Narrative placement:") < instruction.index(
        "Markdown convention:"
    )
    assert "simple italics" in instruction
    assert "ordinary prose and dialogue plain" in instruction
    assert "single quotes, double quotes, or both" in instruction
    assert "speaker-labelled lines, lists, or blockquotes" in instruction
    assert "raw HTML" in instruction


@pytest.mark.parametrize(
    "extra",
    [
        {"dialogue_format": "quoted"},
        {"tone": "playful"},
    ],
)
def test_removed_dialogue_format_and_tone_are_rejected(
    extra: dict[str, str],
) -> None:
    """Reject controls deliberately excluded from the safe vocabulary."""

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ResponseStyleSettings.model_validate(
            {
                "scene_description": "balanced",
                "response_length": "balanced",
                "narrative_placement": "interleaved",
                **extra,
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scene_description", "cinematic"),
        ("response_length", "unlimited"),
        ("narrative_placement", "random"),
    ],
)
def test_unknown_control_values_are_rejected(field: str, value: str) -> None:
    """Reject unknown values instead of silently resolving a fallback."""

    values = {
        "scene_description": "balanced",
        "response_length": "balanced",
        "narrative_placement": "interleaved",
    }
    values[field] = value

    with pytest.raises(ValidationError):
        ResponseStyleSettings.model_validate(values)


def test_equivalent_settings_and_revision_produce_equal_snapshots() -> None:
    """Make effective snapshot equality independent of object identity."""

    current = VersionedResponseStyleSettings(
        settings=default_response_style(ContinuityMode.TIMELINE), revision=4
    )

    assert ResponseStyleRenderer().render(current) == ResponseStyleRenderer().render(
        current.model_copy(deep=True)
    )


def test_style_revision_is_strict_and_positive() -> None:
    """Reject ambiguous or non-positive optimistic style revisions."""

    settings = default_response_style(ContinuityMode.ONGOING)
    with pytest.raises(ValidationError):
        VersionedResponseStyleSettings(settings=settings, revision=0)
    with pytest.raises(ValidationError):
        VersionedResponseStyleSettings(
            settings=settings, revision="1"  # type: ignore[arg-type]
        )


def test_service_loads_updates_and_resolves_complete_settings() -> None:
    """Expose one shared orchestration surface over persistence and rendering."""

    initial = VersionedResponseStyleSettings(
        settings=default_response_style(ContinuityMode.ONGOING), revision=1
    )
    repository = FakeStyleRepository(initial)
    service = ResponseStyleService(repository)
    continuity_id = uuid4()
    replacement = ResponseStyleSettings(
        scene_description=SceneDescriptionLevel.RICH,
        response_length=ResponseLength.EXPANSIVE,
        narrative_placement=NarrativePlacement.AFTER_DIALOGUE,
    )

    result = service.update(continuity_id, replacement, expected_revision=1)

    assert result.status == StyleUpdateStatus.UPDATED
    assert service.get(continuity_id) == result.style
    effective = service.resolve(continuity_id)
    assert effective.source_revision == 2
    assert effective.scene_description == SceneDescriptionLevel.RICH
    assert effective.response_length == ResponseLength.EXPANSIVE
    assert effective.narrative_placement == NarrativePlacement.AFTER_DIALOGUE
