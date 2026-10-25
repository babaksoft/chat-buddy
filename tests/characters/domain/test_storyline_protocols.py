"""Storyline repository boundaries expose only domain-owned contracts."""

import inspect

from chat_buddy.characters.domain import SceneRepository, StorylineRepository


def test_storyline_repository_protocol_covers_lifecycle_boundary() -> None:
    """Expose atomic start, active-slot, metadata, and archival operations."""

    assert StorylineRepository._is_protocol  # type: ignore[attr-defined]
    methods = {name for name, _ in inspect.getmembers(StorylineRepository)}
    assert {
        "start",
        "find_confirmation",
        "find_active",
        "get",
        "list",
        "list_for_pair",
        "rename",
        "archive",
    } <= methods


def test_scene_repository_protocol_covers_order_and_setup_boundary() -> None:
    """Expose owned reads, guarded append, metadata, and setup locking."""

    assert SceneRepository._is_protocol  # type: ignore[attr-defined]
    methods = {name for name, _ in inspect.getmembers(SceneRepository)}
    assert {
        "get",
        "list",
        "append_next",
        "rename",
        "replace_setup",
        "lock_setup",
    } <= methods
