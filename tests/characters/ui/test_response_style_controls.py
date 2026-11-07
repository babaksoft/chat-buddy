"""Acceptance tests for shared response-style controls."""

from unittest.mock import Mock
from uuid import UUID, uuid4

from streamlit.testing.v1 import AppTest

from chat_buddy.characters.application import ResponseStyleService
from chat_buddy.characters.domain import (
    NarrativePlacement,
    ResponseLength,
    ResponseStyleSettings,
    SceneDescriptionLevel,
    StyleUpdateResult,
    StyleUpdateStatus,
    VersionedResponseStyleSettings,
)


def _render(service: object, continuity_id: object, key: object) -> None:
    """Render the focused controls through Streamlit's isolated runner.

    Args:
        service:
            Response-style service double.
        continuity_id:
            Exact continuity owner.
        key:
            Widget namespace.
    """

    from typing import cast
    from uuid import UUID

    from chat_buddy.characters.application import ResponseStyleService
    from chat_buddy.characters.ui.response_style import render_response_style

    render_response_style(
        cast(ResponseStyleService, service),
        cast(UUID, continuity_id),
        cast(str, key),
        False,
    )


def test_saves_complete_style_for_next_response_under_observed_revision() -> None:
    """Preview and save all controls at one optimistic revision."""

    service, continuity_id, current = _service()
    revised = VersionedResponseStyleSettings(
        settings=ResponseStyleSettings(
            scene_description=SceneDescriptionLevel.RICH,
            response_length=ResponseLength.EXPANSIVE,
            narrative_placement=NarrativePlacement.AFTER_DIALOGUE,
        ),
        revision=2,
    )

    def update(
        owner: UUID, settings: ResponseStyleSettings, expected_revision: int
    ) -> StyleUpdateResult:
        """Expose the committed revision on the automatic rerun.

        Args:
            owner:
                Submitted continuity owner.
            settings:
                Submitted complete replacement.
            expected_revision:
                Submitted optimistic guard.

        Returns:
            Successful guarded update.
        """

        assert owner == continuity_id
        assert settings == revised.settings
        assert expected_revision == current.revision
        service.get.return_value = revised
        return StyleUpdateResult(status=StyleUpdateStatus.UPDATED, style=revised)

    service.update.side_effect = update
    app = _app(service, continuity_id, "style_a")
    app.selectbox(key="style_a_scene_description_1").set_value(
        SceneDescriptionLevel.RICH
    )
    app.selectbox(key="style_a_response_length_1").set_value(ResponseLength.EXPANSIVE)
    app.selectbox(key="style_a_narrative_placement_1").set_value(
        NarrativePlacement.AFTER_DIALOGUE
    )
    app.run()
    app.button(key="style_a_save_style_1").click().run()

    service.update.assert_called_once()
    assert not app.exception
    assert any("saved for the next response" in row.value for row in app.success)
    assert not any("Response presentation:" in row.value for row in app.markdown)


def test_stale_revision_keeps_latest_reviewable_without_claiming_success() -> None:
    """Explain a stale style write and avoid a false saved confirmation."""

    service, continuity_id, current = _service()
    service.update.return_value = StyleUpdateResult(
        status=StyleUpdateStatus.STALE_REVISION,
        style=current.model_copy(update={"revision": 2}),
    )
    app = _app(service, continuity_id, "style_b")
    app.selectbox(key="style_b_response_length_1").set_value(ResponseLength.CONCISE)
    app.run()
    app.button(key="style_b_save_style_1").click().run()

    assert any("style changed" in row.value for row in app.warning)
    assert not app.success


def test_widget_namespaces_isolate_continuities() -> None:
    """Keep style input state scoped to the selected continuity page."""

    service, first_id, _ = _service()
    second_id = uuid4()
    app = _app(service, first_id, f"style_{first_id}")
    app.selectbox(key=f"style_{first_id}_response_length_1").set_value(
        ResponseLength.EXPANSIVE
    )
    app.run()

    other = _app(service, second_id, f"style_{second_id}")
    assert (
        other.selectbox(key=f"style_{second_id}_response_length_1").value
        == ResponseLength.BALANCED
    )


def _service() -> tuple[Mock, UUID, VersionedResponseStyleSettings]:
    """Build a style service double with one current revision.

    Returns:
        Service, continuity owner, and current versioned settings.
    """

    current = VersionedResponseStyleSettings(
        settings=ResponseStyleSettings(
            scene_description=SceneDescriptionLevel.BALANCED,
            response_length=ResponseLength.BALANCED,
            narrative_placement=NarrativePlacement.INTERLEAVED,
        ),
        revision=1,
    )
    service = Mock(spec=ResponseStyleService)
    service.get.return_value = current
    return service, uuid4(), current


def _app(service: Mock, continuity_id: UUID, key: str) -> AppTest:
    """Execute the isolated response-style controls.

    Args:
        service:
            Response-style application double.
        continuity_id:
            Exact selected owner.
        key:
            Widget namespace.

    Returns:
        Executed Streamlit test application.
    """

    return AppTest.from_function(
        _render,
        args=(service, continuity_id, key),
        default_timeout=10,
    ).run()
