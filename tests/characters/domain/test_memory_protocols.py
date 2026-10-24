"""Storyline memory strategy and repository boundary tests."""

import inspect

from chat_buddy.characters.domain import (
    MemoryContextSelector,
    MemoryDeltaExtractor,
    MemoryExtractionRepository,
    StorylineMemoryRepository,
)


def test_context_selector_and_delta_extractor_are_separate_protocols() -> None:
    """Keep selection substitutable independently from model-backed extraction."""

    assert MemoryContextSelector._is_protocol  # type: ignore[attr-defined]
    assert MemoryDeltaExtractor._is_protocol  # type: ignore[attr-defined]
    selector_methods = {name for name, _ in inspect.getmembers(MemoryContextSelector)}
    extractor_methods = {name for name, _ in inspect.getmembers(MemoryDeltaExtractor)}
    assert "select" in selector_methods
    assert "extract" not in selector_methods
    assert "extract" in extractor_methods
    assert "select" not in extractor_methods


def test_memory_repositories_cover_lifecycle_effects_and_conflicts() -> None:
    """Expose narrow persistence boundaries without implementation types."""

    assert StorylineMemoryRepository._is_protocol  # type: ignore[attr-defined]
    assert MemoryExtractionRepository._is_protocol  # type: ignore[attr-defined]
    memory_methods = {name for name, _ in inspect.getmembers(StorylineMemoryRepository)}
    extraction_methods = {
        name for name, _ in inspect.getmembers(MemoryExtractionRepository)
    }
    assert {"get", "list", "list_eligible", "correct", "change_state", "delete"} <= (
        memory_methods
    )
    assert {"reserve", "get_effect", "apply", "list_conflicts", "dismiss_conflict"} <= (
        extraction_methods
    )
