"""Shared continuity-scoped response-style controls."""

from typing import cast
from uuid import UUID

import streamlit as st

from chat_buddy.characters.application import ResponseStyleService
from chat_buddy.characters.domain import (
    NarrativePlacement,
    ResponseLength,
    ResponseStyleSettings,
    SceneDescriptionLevel,
    StyleUpdateStatus,
)


def render_response_style(
    service: ResponseStyleService,
    continuity_id: UUID,
    key: str,
    disabled: bool,
) -> None:
    """Render and persist all presentation controls for one continuity.

    Args:
        service:
            Continuity-scoped style operations.
        continuity_id:
            Exact owning Characters continuity.
        key:
            Ownership-scoped widget namespace.
        disabled:
            Whether lifecycle state prevents updates.
    """

    current = service.get(continuity_id)
    settings = current.settings
    with st.expander("Response style"):
        st.caption(
            "These controls affect the next newly reserved persona response. "
            "Saved responses keep the style that generated them."
        )
        scene_description = cast(
            SceneDescriptionLevel,
            st.selectbox(
                "Scene description",
                tuple(SceneDescriptionLevel),
                index=tuple(SceneDescriptionLevel).index(settings.scene_description),
                format_func=_label,
                disabled=disabled,
                key=f"{key}_scene_description_{current.revision}",
            ),
        )
        response_length = cast(
            ResponseLength,
            st.selectbox(
                "Response length",
                tuple(ResponseLength),
                index=tuple(ResponseLength).index(settings.response_length),
                format_func=_label,
                disabled=disabled,
                key=f"{key}_response_length_{current.revision}",
            ),
        )
        narrative_placement = cast(
            NarrativePlacement,
            st.selectbox(
                "Narrative placement",
                tuple(NarrativePlacement),
                index=tuple(NarrativePlacement).index(settings.narrative_placement),
                format_func=_label,
                disabled=disabled,
                key=f"{key}_narrative_placement_{current.revision}",
            ),
        )
        requested = ResponseStyleSettings(
            scene_description=scene_description,
            response_length=response_length,
            narrative_placement=narrative_placement,
        )
        _preview(requested)
        if st.button(
            "Save response style",
            disabled=disabled or requested == settings,
            key=f"{key}_save_style_{current.revision}",
        ):
            result = service.update(continuity_id, requested, current.revision)
            if result.status == StyleUpdateStatus.STALE_REVISION:
                st.warning("The response style changed. Review the latest values.")
            elif result.status == StyleUpdateStatus.ARCHIVED:
                st.warning("Archived continuities cannot change response style.")
            else:
                st.session_state[f"{key}_style_saved"] = True
                st.rerun()
        if st.session_state.pop(f"{key}_style_saved", False):
            st.success("Response style saved for the next response.")


def _preview(settings: ResponseStyleSettings) -> None:
    """Explain effective controls without exposing internal prompt text.

    Args:
        settings:
            Complete requested controls selected in the widgets.
    """

    descriptions = {
        SceneDescriptionLevel.NONE: "No narrated action or environment",
        SceneDescriptionLevel.LIGHT: "Brief description when useful",
        SceneDescriptionLevel.BALANCED: "Relevant description without dominance",
        SceneDescriptionLevel.RICH: "Substantial descriptive detail",
    }
    lengths = {
        ResponseLength.CONCISE: "Concise and focused",
        ResponseLength.BALANCED: "Balanced detail",
        ResponseLength.EXPANSIVE: "Developed and expansive",
    }
    placements = {
        NarrativePlacement.BEFORE_DIALOGUE: "Description before dialogue",
        NarrativePlacement.INTERLEAVED: "Description interleaved with dialogue",
        NarrativePlacement.AFTER_DIALOGUE: "Description after dialogue",
    }
    st.markdown("**Effective preview**")
    st.caption(
        f"{descriptions[settings.scene_description]} · "
        f"{lengths[settings.response_length]} · "
        f"{placements[settings.narrative_placement]}"
    )
    st.caption(
        "Description uses ordinary Markdown italics; dialogue remains plain text. "
        "Tone continues to come from the persona and relationship."
    )


def _label(value: object) -> str:
    """Return a readable label for one string enum.

    Args:
        value:
            Enum value supplied by Streamlit.

    Returns:
        Capitalized human-readable label.
    """

    return str(getattr(value, "value", value)).replace("_", " ").capitalize()
