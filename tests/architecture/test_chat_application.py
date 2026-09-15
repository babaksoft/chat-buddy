"""Architecture checks for the canonical Chat application layer."""

import ast
import importlib
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "chat_buddy"
APPLICATION_ROOT = PACKAGE_ROOT / "chat" / "application"
ALLOWED_CHAT_DEPENDENCIES = (
    "chat_buddy.chat.application",
    "chat_buddy.chat.domain",
    "chat_buddy.chat.prompts",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }


def test_chat_application_has_only_inward_chat_dependencies() -> None:
    violations = [
        f"{path.relative_to(PACKAGE_ROOT)} imports {imported_module}"
        for path in sorted(APPLICATION_ROOT.rglob("*.py"))
        for imported_module in sorted(_imports(path))
        if imported_module.startswith("chat_buddy.")
        and not imported_module.startswith(ALLOWED_CHAT_DEPENDENCIES)
    ]

    assert violations == []


@pytest.mark.parametrize(
    ("legacy_module", "canonical_module", "export_name"),
    [
        ("application.config", "chat.application.config", "ContextBuilderConfig"),
        ("application.config", "chat.application.config", "MemoryConfig"),
        (
            "application.context_builder",
            "chat.application.context_builder",
            "DefaultContextBuilder",
        ),
        (
            "application.llm_summarizer",
            "chat.application.llm_summarizer",
            "LLMSummarizer",
        ),
        ("application.schemas", "chat.application.schemas", "ChatRequest"),
        ("application.schemas", "chat.application.schemas", "ChatResponse"),
        (
            "application.schemas",
            "chat.application.schemas",
            "ConversationEntry",
        ),
        ("application.service", "chat.application.service", "ChatService"),
        (
            "application.service",
            "chat.application.service",
            "ConversationService",
        ),
        ("application.service", "chat.application.service", "MemoryService"),
    ],
)
def test_legacy_paths_reexport_canonical_objects(
    legacy_module: str,
    canonical_module: str,
    export_name: str,
) -> None:
    legacy = importlib.import_module(f"chat_buddy.{legacy_module}")
    canonical = importlib.import_module(f"chat_buddy.{canonical_module}")

    assert getattr(legacy, export_name) is getattr(canonical, export_name)
