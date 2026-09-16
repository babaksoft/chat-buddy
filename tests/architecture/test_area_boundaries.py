"""Architecture checks for the Stage 1 product-area boundaries."""

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[2] / "src"
PROJECT_ROOT = SOURCE_ROOT.parent
PACKAGE_ROOT = SOURCE_ROOT / "chat_buddy"
SHELL_MODULE = "chat_buddy.ui.streamlit_app"
AREA_PREFIXES = {
    "chat": "chat_buddy.chat",
    "characters": "chat_buddy.characters",
    "shared": "chat_buddy.shared",
}

REMOVED_TRANSITION_PATHS = (
    PACKAGE_ROOT / "application",
    PACKAGE_ROOT / "domain",
    PACKAGE_ROOT / "infrastructure",
    PACKAGE_ROOT / "prompts",
    PACKAGE_ROOT / "ui" / "pages",
)


def _module_name(path: Path) -> str:
    relative_path = path.relative_to(SOURCE_ROOT).with_suffix("")
    parts = relative_path.parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_from_import(
    module_name: str, node: ast.ImportFrom, *, is_package: bool
) -> str:
    if node.level == 0:
        return node.module or ""

    package_parts = module_name.split(".")
    if not is_package:
        package_parts = package_parts[:-1]
    retained_parts = package_parts[: len(package_parts) - node.level + 1]
    if node.module:
        retained_parts.extend(node.module.split("."))
    return ".".join(retained_parts)


def _imports(path: Path) -> set[str]:
    module_name = _module_name(path)
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    imported_modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_module = _resolve_from_import(
                module_name,
                node,
                is_package=path.name == "__init__.py",
            )
            imported_modules.add(imported_module)
            imported_modules.update(
                f"{imported_module}.{alias.name}"
                for alias in node.names
                if alias.name != "*"
            )

    return imported_modules


def _area(module_name: str) -> str | None:
    for area, prefix in AREA_PREFIXES.items():
        if module_name == prefix or module_name.startswith(f"{prefix}."):
            return area
    return None


def _boundary_violations() -> list[str]:
    violations: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        source_module = _module_name(path)
        source_area = _area(source_module)

        if source_module == SHELL_MODULE:
            continue

        for imported_module in sorted(_imports(path)):
            imported_area = _area(imported_module)
            if imported_area is None:
                continue
            if source_area is None:
                violations.append(f"{source_module} imports {imported_module}")
                continue
            if imported_area == source_area:
                continue
            if source_area in {"chat", "characters"} and imported_area == "shared":
                continue
            violations.append(f"{source_module} imports {imported_module}")

    return violations


def test_product_areas_do_not_import_each_other() -> None:
    assert _boundary_violations() == []


def test_transition_packages_are_removed() -> None:
    assert [path for path in REMOVED_TRANSITION_PATHS if any(path.rglob("*.py"))] == []


def test_only_area_specific_alembic_targets_are_active() -> None:
    assert not (PROJECT_ROOT / "alembic.ini").exists()
    assert not (PROJECT_ROOT / "alembic" / "env.py").exists()
    assert not (PROJECT_ROOT / "alembic" / "script.py.mako").exists()
    assert (PROJECT_ROOT / "alembic-chat.ini").is_file()
    assert (PROJECT_ROOT / "alembic-characters.ini").is_file()
    assert {
        path.name for path in (PROJECT_ROOT / "alembic" / "versions").glob("*.py")
    } == {
        "00583eb3ed81_add_memories_table.py",
        "8c080da941a4_create_conversations_and_messages_tables.py",
        "b9fc65d514ec_add_system_role.py",
    }
