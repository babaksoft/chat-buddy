"""Architecture checks for the Stage 1 product-area boundaries."""

import ast
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).parents[2] / "src"
PACKAGE_ROOT = SOURCE_ROOT / "chat_buddy"
SHELL_MODULE = "chat_buddy.ui.streamlit_app"
AREA_PREFIXES = {
    "chat": "chat_buddy.chat",
    "characters": "chat_buddy.characters",
    "shared": "chat_buddy.shared",
}

# These packages contain the pre-split Chat implementation. They remain outside
# strict area ownership until their dedicated Stage 1 move slices are complete.
LEGACY_IMPORT_WHITELIST = frozenset(
    {
        "chat_buddy.application",
        "chat_buddy.domain",
        "chat_buddy.infrastructure",
        "chat_buddy.prompts",
        "chat_buddy.ui.pages.chat",
    }
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
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
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


def _is_legacy(module_name: str) -> bool:
    return any(
        module_name == prefix or module_name.startswith(f"{prefix}.")
        for prefix in LEGACY_IMPORT_WHITELIST
    )


def _boundary_violations() -> list[str]:
    violations: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        source_module = _module_name(path)
        source_area = _area(source_module)

        if source_module == SHELL_MODULE or _is_legacy(source_module):
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


@pytest.mark.parametrize("legacy_prefix", sorted(LEGACY_IMPORT_WHITELIST))
def test_legacy_import_whitelist_names_existing_modules(legacy_prefix: str) -> None:
    module_path = SOURCE_ROOT / Path(*legacy_prefix.split("."))
    assert module_path.with_suffix(".py").exists() or module_path.is_dir()
