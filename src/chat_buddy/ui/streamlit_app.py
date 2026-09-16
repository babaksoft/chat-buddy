"""Routing-only Streamlit shell for Chat Buddy."""

import streamlit as st

from chat_buddy.characters.ui import render as render_characters
from chat_buddy.chat.ui import render as render_chat
from chat_buddy.shared.config.logging import configure_logging

configure_logging()


def main() -> None:
    """Configure the shared shell and render the selected application area."""

    st.set_page_config(
        page_title="Chat Buddy",
        page_icon="💬",
    )

    page = st.navigation(
        [
            st.Page(render_chat, title="Chat", icon="💬", default=True),
            st.Page(
                render_characters,
                title="Characters",
                icon="👥",
                url_path="characters",
            ),
        ],
        position="sidebar",
    )
    page.run()


if __name__ == "__main__":
    main()
