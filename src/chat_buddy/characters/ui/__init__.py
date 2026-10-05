"""User interface for the Characters area."""

from chat_buddy.characters.ui.identities_page import render_identities
from chat_buddy.characters.ui.new_ongoing_page import render_new_ongoing
from chat_buddy.characters.ui.ongoing_page import render_ongoing_page
from chat_buddy.characters.ui.page import render
from chat_buddy.characters.ui.personas_page import render_personas

__all__ = [
    "render",
    "render_identities",
    "render_new_ongoing",
    "render_ongoing_page",
    "render_personas",
]
