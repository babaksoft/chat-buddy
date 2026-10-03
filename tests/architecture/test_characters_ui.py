"""Characters UI architecture and lazy composition requirements."""

import ast
import subprocess
import sys
from pathlib import Path


def test_ui_uses_application_services_without_database_or_provider_access() -> None:
    """Reject persistence, SDK, and cross-area imports in Characters UI."""

    root = Path(__file__).parents[2] / "src/chat_buddy/characters/ui"
    forbidden = (
        "sqlalchemy",
        "ollama",
        "chat_buddy.chat",
        "chat_buddy.characters.infrastructure.db",
        "chat_buddy.characters.infrastructure.llm",
    )
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            )
            assert not any(module.startswith(forbidden) for module in modules), path
            if isinstance(node, ast.ImportFrom):
                assert not any("Repository" in alias.name for alias in node.names), path


def test_importing_characters_ui_does_not_initialize_persistence_or_chat() -> None:
    """Import the route in a fresh interpreter without initializing either area."""

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import chat_buddy.characters.ui; assert 'chat_buddy.characters.infrastructure.db.session' not in sys.modules; assert not any(name.startswith('chat_buddy.chat') for name in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
