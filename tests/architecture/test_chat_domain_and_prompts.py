"""Architecture checks for the canonical Chat domain and prompts."""

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "chat_buddy"
CHAT_ROOT = PACKAGE_ROOT / "chat"
FORBIDDEN_DEPENDENCIES = (
    "chat_buddy.characters",
    "chat_buddy.chat.application",
    "chat_buddy.chat.infrastructure",
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
