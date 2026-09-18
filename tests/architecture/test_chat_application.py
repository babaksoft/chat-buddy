"""Architecture checks for the canonical Chat application layer."""

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "chat_buddy"
APPLICATION_ROOT = PACKAGE_ROOT / "chat" / "application"
UI_ROOTS = (PACKAGE_ROOT / "chat" / "ui", PACKAGE_ROOT / "ui")
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


def test_application_and_ui_do_not_import_ollama_sdk_or_adapter() -> None:
    """Keep provider clients and concrete adapter types in infrastructure."""

    roots = (APPLICATION_ROOT, *UI_ROOTS)
    violations = [
        f"{path.relative_to(PACKAGE_ROOT)} imports {imported_module}"
        for root in roots
        for path in sorted(root.rglob("*.py"))
        for imported_module in sorted(_imports(path))
        if imported_module == "ollama"
        or imported_module.startswith("ollama.")
        or imported_module.endswith("ollama_gateway")
    ]
    adapter_name_violations = [
        str(path.relative_to(PACKAGE_ROOT))
        for root in roots
        for path in sorted(root.rglob("*.py"))
        if "OllamaGateway" in path.read_text(encoding="utf-8-sig")
    ]

    assert violations == []
    assert adapter_name_violations == []


def test_ollama_sdk_is_confined_to_its_infrastructure_adapter() -> None:
    """Prevent provider SDK imports from escaping the concrete adapter."""

    allowed_path = (
        PACKAGE_ROOT / "chat" / "infrastructure" / "llm" / "ollama_gateway.py"
    )
    violations = [
        f"{path.relative_to(PACKAGE_ROOT)} imports {imported_module}"
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if path != allowed_path
        for imported_module in sorted(_imports(path))
        if imported_module == "ollama" or imported_module.startswith("ollama.")
    ]

    assert violations == []
