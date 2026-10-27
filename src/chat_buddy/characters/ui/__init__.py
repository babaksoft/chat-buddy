"""User interface for the Characters area."""

from chat_buddy.characters.ui.identities_page import render_identities
from chat_buddy.characters.ui.new_ongoing_page import render_new_ongoing
from chat_buddy.characters.ui.new_storyline_page import render_new_storyline
from chat_buddy.characters.ui.ongoing_page import render_ongoing_page
from chat_buddy.characters.ui.personas_page import render_personas
from chat_buddy.characters.ui.storylines_page import render_storylines_page

__all__ = [
    "render_identities",
    "render_new_ongoing",
    "render_new_storyline",
    "render_ongoing_page",
    "render_personas",
    "render_storylines_page",
]
