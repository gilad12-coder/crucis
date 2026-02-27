"""Shared fixtures for Crucis MCP server tests."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest_asyncio
from mcp.shared.memory import create_connected_server_and_client_session


def _write_minimal_workspace(ws: Path) -> None:
    """Create a minimal Crucis workspace with objective + profiles.

    Args:
        ws: Workspace root directory.
    """
    ws.mkdir(parents=True, exist_ok=True)
    (ws / ".crucis").mkdir(exist_ok=True)
    (ws / "objective.yaml").write_text(
        textwrap.dedent("""\
            name: add
            description: Add two numbers
            signature: "def add(a: int, b: int) -> int"
            tasks:
              - name: add
                description: Add two numbers
                signature: "def add(a: int, b: int) -> int"
                train_evals:
                  - input: "(1, 2)"
                    output: "3"
                holdout_evals:
                  - input: "(10, 20)"
                    output: "30"
                target_files:
                  - src/solution.py
        """),
        encoding="utf-8",
    )
    (ws / "profiles.yaml").write_text(
        textwrap.dedent("""\
            default:
              tests:
                primary:
                  max_cyclomatic_complexity: 10
                  max_lines_per_function: 50
                secondary:
                  require_docstrings: true
              implementation:
                primary:
                  max_cyclomatic_complexity: 10
                secondary:
                  require_docstrings: true
        """),
        encoding="utf-8",
    )
    src = ws / "src"
    src.mkdir(exist_ok=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "solution.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n",
        encoding="utf-8",
    )


@pytest_asyncio.fixture
async def mcp_client(tmp_path, monkeypatch):
    """In-memory MCP client connected to the Crucis server.

    Creates a minimal workspace in tmp_path and configures env vars.

    Args:
        tmp_path: Temporary directory for the workspace.
        monkeypatch: Pytest monkeypatch fixture.

    Yields:
        Tuple of (ClientSession, workspace Path).
    """
    _write_minimal_workspace(tmp_path)
    monkeypatch.setenv("CRUCIS_MCP_AUTHORIZED", "1")
    monkeypatch.setenv("CRUCIS_WORKSPACE", str(tmp_path))

    from crucis.mcp.server import mcp as server

    try:
        async with create_connected_server_and_client_session(server) as client:
            await client.initialize()
            yield client, tmp_path
    except RuntimeError:
        # anyio cancel scope teardown can raise in pytest-asyncio fixtures
        pass


def parse_tool_result(result) -> dict:
    """Extract and parse JSON dict from a CallToolResult.

    Args:
        result: MCP CallToolResult from call_tool().

    Returns:
        Parsed dict from the JSON text content.
    """
    return json.loads(result.content[0].text)
