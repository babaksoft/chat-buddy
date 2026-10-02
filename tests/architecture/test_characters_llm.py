"""Characters LLM layer isolation and lazy composition checks."""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_provider_sdks_stay_in_characters_infrastructure() -> None:
    """Reject provider SDK imports from domain, application, prompts, and UI."""

    violations: list[tuple[Path, str]] = []
    for layer in ("domain", "application", "prompts", "ui"):
        for path in (ROOT / "src/chat_buddy/characters" / layer).rglob("*.py"):
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
                violations.extend(
                    (path, module)
                    for module in modules
                    if module.split(".")[0]
                    in {"ollama", "openai", "httpx", "requests", "boto3"}
                )
    assert violations == []


def test_importing_characters_composition_constructs_no_clients() -> None:
    """Import the resolver factory in a fresh process with client guards."""

    script = """
from unittest.mock import patch
with patch("ollama.Client", side_effect=AssertionError("eager client")):
    import chat_buddy.characters.infrastructure.llm.configured_providers
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
