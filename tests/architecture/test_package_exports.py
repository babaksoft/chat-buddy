"""Architecture symbols use their owning package's explicit public boundary."""

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
SRC = ROOT / "src"
PACKAGE_ROOT = SRC / "chat_buddy"


def test_architecture_symbols_are_exported_by_their_owning_package() -> None:
    """Require public layer types, factories, and prompts in package exports."""

    violations = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if path.name == "__init__.py" or not any(
            layer in path.relative_to(PACKAGE_ROOT).parts
            for layer in ("domain", "application", "infrastructure", "prompts")
        ):
            continue
        boundary = path.parent / "__init__.py"
        package = ".".join(path.parent.relative_to(SRC).parts)
        exports = _exports(boundary)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in tree.body:
            if (
                isinstance(node, (ast.ClassDef, ast.FunctionDef))
                and not node.name.startswith("_")
                and (f"{package}.{path.stem}", node.name) not in exports
            ):
                violations.append(f"{path.relative_to(ROOT)}: {node.name}")
    assert violations == []


def test_external_architecture_imports_use_package_boundaries() -> None:
    """Prevent exported implementation symbols from bypassing package boundaries."""

    boundaries = {}
    for boundary in PACKAGE_ROOT.rglob("__init__.py"):
        package = ".".join(boundary.parent.relative_to(SRC).parts)
        for exported_symbol in _exports(boundary):
            boundaries[exported_symbol] = package
    paths = [
        *PACKAGE_ROOT.rglob("*.py"),
        *(ROOT / "tests").rglob("*.py"),
        *(ROOT / "alembic").glob("*/env.py"),
    ]
    violations = []
    for path in paths:
        consumer = (
            ".".join(path.parent.relative_to(SRC).parts)
            if path.is_relative_to(SRC)
            else None
        )
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            for symbol in node.names:
                owning_package = boundaries.get((node.module, symbol.name))
                if owning_package is not None and consumer != owning_package:
                    violations.append(
                        f"{path.relative_to(ROOT)} imports {node.module}.{symbol.name}; use {owning_package}"
                    )
    assert violations == []


def _exports(path: Path) -> set[tuple[str, str]]:
    """Read explicit implementation reexports without importing runtime packages.

    Args:
        path:
            Package initializer to inspect.

    Returns:
        Implementation module and symbol pairs declared in the public API.
    """

    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    public = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            public.update(ast.literal_eval(node.value))
    return {
        (node.module, symbol.name)
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
        for symbol in node.names
        if (symbol.asname or symbol.name) in public
    }
