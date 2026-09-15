"""Landing page for future character profiles and conversations."""

import streamlit as st


def render() -> None:
    """Render the Characters scaffold without initializing Chat services."""

    st.title("👥 Characters")
    st.write(
        "Create character profiles and have conversations with them. "
        "Character setup and conversations are coming next."
    )
