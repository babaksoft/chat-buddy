"""Characters domain and fixture independence checks."""

import ast
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]


def test_characters_domain_imports_no_outward_layers() -> None:
    """Domain values and protocols depend only on inward or standard libraries."""

    violations = []
    for path in (PROJECT_ROOT / "src/chat_buddy/characters/domain").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else []
                )
            )
            for module in modules:
                if module.startswith(
                    ("sqlalchemy", "streamlit", "ollama", "chat_buddy.")
                ) and not module.startswith("chat_buddy.characters.domain"):
                    violations.append((str(path), module))
    assert violations == []


def test_characters_fixture_collection_and_execution_do_not_import_chat() -> None:
    """Execute isolated Characters tests while rejecting every Chat import."""

    script = '''
import importlib.abc
import sys
class RejectChat(importlib.abc.MetaPathFinder):
    """Prevent isolated Characters tests from importing any Chat module."""

    def find_spec(
        self, fullname: str, path: object = None, target: object = None
    ) -> None:
        """Reject Chat module discovery while allowing other finders to proceed.

        Args:
            fullname:
                Fully qualified module name being resolved.
            path:
                Optional package search path supplied by the importer.
            target:
                Optional module being reloaded.

        Raises:
            AssertionError:
                If a Characters test attempts to import Chat.
        """

        if fullname == "chat_buddy.chat" or fullname.startswith("chat_buddy.chat."):
            raise AssertionError("Characters initialized Chat: " + fullname)
sys.meta_path.insert(0, RejectChat())
import pytest
sys.exit(pytest.main(["tests/characters", "tests/integration/characters", "-m", "not characters_postgres", "-q"]))
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
