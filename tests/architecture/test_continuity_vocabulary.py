"""Guard the shared Continuity architecture against transitional names."""

import ast
from pathlib import Path


def test_obsolete_continuity_symbols_are_absent() -> None:
    """Production code must use the shared Entry and Continuity vocabulary."""

    obsolete = {
        "create_storyline_memory_service",
        "create_timeline_memory_service",
        "ScenePosition",
        "DayPosition",
        "MemoryPosition",
        "StorylineMemory",
        "TimelineMemory",
        "StorylineMemoryRepository",
        "TimelineMemoryRepository",
        "DbStorylineMemoryRepository",
        "DbTimelineMemoryRepository",
        "StorylineMemoryService",
        "TimelineMemoryService",
        "StorylineMemoryEligibility",
        "TimelineMemoryEligibility",
        "StorylineMemoryExtractionService",
        "TimelineMemoryExtractionService",
        "BaselineTimelineMemoryContextSelector",
    }
    root = Path(__file__).resolve().parents[2] / "src/chat_buddy/characters"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in obsolete, (path, node.id)
            elif isinstance(node, (ast.alias, ast.ClassDef, ast.FunctionDef)):
                assert node.name not in obsolete, (path, node.name)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in obsolete | {"storyline_memories"}, (
                    path,
                    node.value,
                )


def test_shared_contracts_do_not_pair_scene_and_day_fields() -> None:
    """Require one Entry owner rather than parallel optional subtype owners."""

    root = Path(__file__).resolve().parents[2] / "src/chat_buddy/characters"
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.ClassDef):
                continue
            fields = {
                child.target.id
                for child in node.body
                if isinstance(child, ast.AnnAssign)
                and isinstance(child.target, ast.Name)
            }
            assert not {"scene_id", "day_id"} <= fields, (path, node.name)
            assert not {"occurrence_scene_id", "occurrence_day_id"} <= fields, (
                path,
                node.name,
            )
            assert not {"learned_scene_id", "learned_day_id"} <= fields, (
                path,
                node.name,
            )


def test_shared_prompts_and_evolution_use_entry_provenance() -> None:
    """Reject subtype introspection and obsolete evolution source fields."""

    root = Path(__file__).resolve().parents[2] / "src/chat_buddy/characters"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if "prompts" in path.parts and isinstance(node, ast.Call):
                assert not (
                    isinstance(node.func, ast.Name) and node.func.id == "hasattr"
                ), path
            if "evolution" in path.stem:
                names = set()
                if isinstance(node, ast.Name):
                    names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    names.add(node.attr)
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    names.add(node.value)
                assert names.isdisjoint(
                    {
                        "scene_id",
                        "scene_position",
                        "storyline_checkpoint",
                        "STORYLINE_CHECKPOINT",
                    }
                ), (path, names)
