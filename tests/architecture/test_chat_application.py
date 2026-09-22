"""Architecture checks for the canonical Chat application layer."""

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "chat_buddy"
APPLICATION_ROOT = PACKAGE_ROOT / "chat" / "application"
UI_ROOTS = (PACKAGE_ROOT / "chat" / "ui", PACKAGE_ROOT / "ui")
PROVISIONAL_PATHS = (
    APPLICATION_ROOT / "service" / "memory_service.py",
    PACKAGE_ROOT / "chat" / "domain" / "extracted_memory.py",
    PACKAGE_ROOT / "chat" / "domain" / "summarizer.py",
)
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


def test_application_and_ui_do_not_import_provider_sdks_or_adapters() -> None:
    """Keep provider clients and concrete adapter types in infrastructure."""

    roots = (APPLICATION_ROOT, *UI_ROOTS)
    violations = [
        f"{path.relative_to(PACKAGE_ROOT)} imports {imported_module}"
        for root in roots
        for path in sorted(root.rglob("*.py"))
        for imported_module in sorted(_imports(path))
        if imported_module in {"ollama", "openai", "tiktoken"}
        or imported_module.startswith(("ollama.", "openai.", "tiktoken."))
        or imported_module.endswith(("ollama_gateway", "openai_gateway"))
    ]
    adapter_name_violations = [
        str(path.relative_to(PACKAGE_ROOT))
        for root in roots
        for path in sorted(root.rglob("*.py"))
        if any(
            name in path.read_text(encoding="utf-8-sig")
            for name in ("OllamaGateway", "OpenAIResponseGateway")
        )
    ]

    assert violations == []
    assert adapter_name_violations == []


def test_application_and_ui_do_not_access_sqlalchemy_directly() -> None:
    """Keep persistence access behind Chat-owned repository contracts."""

    roots = (APPLICATION_ROOT, *UI_ROOTS)
    violations = [
        f"{path.relative_to(PACKAGE_ROOT)} imports {imported_module}"
        for root in roots
        for path in sorted(root.rglob("*.py"))
        for imported_module in sorted(_imports(path))
        if imported_module == "sqlalchemy" or imported_module.startswith("sqlalchemy.")
    ]

    assert violations == []


def test_stage_three_provisional_paths_are_removed() -> None:
    """Prevent compatibility APIs from bypassing lifecycle and provenance."""

    from chat_buddy.chat.infrastructure.db.repositories import MemoryRepository

    assert [path for path in PROVISIONAL_PATHS if path.exists()] == []
    assert not hasattr(MemoryRepository, "save_memory")
    assert not hasattr(MemoryRepository, "get_memories")
    assert not hasattr(MemoryRepository, "delete_memory")


def test_chat_ui_views_do_not_import_infrastructure() -> None:
    """Keep repository and provider construction in the composition root."""

    ui_root = PACKAGE_ROOT / "chat" / "ui"
    view_paths = [
        path for path in sorted(ui_root.rglob("*.py")) if path.name != "composition.py"
    ]
    violations = [
        f"{path.relative_to(PACKAGE_ROOT)} imports {imported_module}"
        for path in view_paths
        for imported_module in sorted(_imports(path))
        if imported_module.startswith("chat_buddy.chat.infrastructure")
    ]

    assert violations == []


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


def test_openai_sdk_is_confined_to_its_infrastructure_adapter() -> None:
    """Prevent the cloud SDK from escaping the concrete response adapter."""

    allowed_path = (
        PACKAGE_ROOT / "chat" / "infrastructure" / "llm" / "openai_gateway.py"
    )
    violations = [
        f"{path.relative_to(PACKAGE_ROOT)} imports {imported_module}"
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if path != allowed_path
        for imported_module in sorted(_imports(path))
        if imported_module == "openai" or imported_module.startswith("openai.")
    ]

    assert violations == []
