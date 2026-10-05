"""User interface for the Characters area."""

from chat_buddy.characters.ui.identities_page import render_identities
from chat_buddy.characters.ui.page import render
from chat_buddy.characters.ui.personas_page import render_personas

__all__ = ["render", "render_identities", "render_personas"]
