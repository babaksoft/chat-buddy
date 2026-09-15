"""Architecture checks for the canonical Chat domain and prompts."""

import ast
import importlib
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "chat_buddy"
CHAT_ROOT = PACKAGE_ROOT / "chat"
FORBIDDEN_DEPENDENCIES = (
    "chat_buddy.application",
    "chat_buddy.characters",
    "chat_buddy.infrastructure",
    "chat_buddy.shared",
    "chat_buddy.ui",
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


def test_chat_domain_and_prompts_have_no_outward_dependencies() -> None:
    violations = [
        f"{path.relative_to(PACKAGE_ROOT)} imports {imported_module}"
        for package_name in ("domain", "prompts")
        for path in sorted((CHAT_ROOT / package_name).rglob("*.py"))
        for imported_module in sorted(_imports(path))
        if imported_module.startswith(FORBIDDEN_DEPENDENCIES)
    ]

    assert violations == []


@pytest.mark.parametrize(
    ("legacy_module", "canonical_module", "export_name"),
    [
        ("domain.chat", "chat.domain.chat", "ChatMessage"),
        ("domain.chat", "chat.domain.chat", "ChatRole"),
        ("domain.context_builder", "chat.domain.context_builder", "ContextBuilder"),
        (
            "domain.exceptions",
            "chat.domain.exceptions",
            "ContextWindowExceededError",
        ),
        (
            "domain.extracted_memory",
            "chat.domain.extracted_memory",
            "ExtractedMemory",
        ),
        ("domain.llm_gateway", "chat.domain.llm_gateway", "LLMGateway"),
        (
            "domain.repositories",
            "chat.domain.repositories",
            "ConversationRecord",
        ),
        (
            "domain.repositories",
            "chat.domain.repositories",
            "ConversationRepository",
        ),
        ("domain.repositories", "chat.domain.repositories", "MemoryRecord"),
        ("domain.repositories", "chat.domain.repositories", "MemoryRepository"),
        ("domain.repositories", "chat.domain.repositories", "MessageRecord"),
        ("domain.summarizer", "chat.domain.summarizer", "Summarizer"),
        ("domain.tokenizer", "chat.domain.tokenizer", "TokenCounter"),
        ("domain.tokenizer", "chat.domain.tokenizer", "TokenUsage"),
        (
            "prompts.memory",
            "chat.prompts.memory",
            "EXTRACT_MEMORY_PROMPT",
        ),
        (
            "prompts.memory",
            "chat.prompts.memory",
            "MEMORY_CONTEXT_HEADER",
        ),
        ("prompts.summary", "chat.prompts.summary", "SUMMARIZE_PROMPT"),
        ("prompts.title", "chat.prompts.title", "GENERATE_TITLE_PROMPT"),
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
