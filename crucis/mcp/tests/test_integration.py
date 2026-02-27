"""Integration test: full workflow through MCP tools."""

from __future__ import annotations

import textwrap

import pytest

from crucis.mcp.tests.conftest import parse_tool_result

pytestmark = pytest.mark.timeout(30)


_TEST_SOURCE = textwrap.dedent("""\
    \"\"\"Tests for the add function.\"\"\"

    from src.solution import add


    def test_add_basic():
        \"\"\"Verify basic addition.\"\"\"
        assert add(1, 2) == 3


    def test_add_negative():
        \"\"\"Verify negative number addition.\"\"\"
        assert add(-1, -2) == -3


    def test_add_zero():
        \"\"\"Verify addition with zero.\"\"\"
        assert add(0, 0) == 0
""")


def _assert_error_envelope(data: dict) -> None:
    """Verify every error response has the standard envelope fields."""
    assert "error" in data
    assert "error_type" in data
    assert isinstance(data["error"], str)
    assert isinstance(data["error_type"], str)


@pytest.mark.asyncio
async def test_full_workflow(mcp_client):
    """Walk the full MCP workflow: validate → prompt → submit → adversary → verify.

    Args:
        mcp_client: In-memory MCP client fixture.
    """
    client, ws = mcp_client

    # 1. Validate objective
    result = await client.call_tool("crucis_validate", {"workspace": str(ws)})
    data = parse_tool_result(result)
    assert data["valid"] is True
    assert data["name"] == "add"

    # 2. Get generation prompt
    result = await client.call_tool(
        "crucis_get_prompt",
        {"step": "generation", "task_name": "add", "workspace": str(ws)},
    )
    data = parse_tool_result(result)
    assert "prompt" in data
    assert len(data["prompt"]) > 0

    # 3. Submit a hand-written test suite
    result = await client.call_tool(
        "crucis_submit_test_suite",
        {"task_name": "add", "test_source": _TEST_SOURCE, "workspace": str(ws)},
    )
    data = parse_tool_result(result)
    assert data.get("accepted") is True, f"submit_test_suite failed: {data}"

    # 4. Submit adversarial report
    result = await client.call_tool(
        "crucis_submit_adversarial_report",
        {
            "task_name": "add",
            "attack_vectors": ["hardcoded return values"],
            "generalization_gaps": ["no large number tests"],
            "suggested_probe_tests": ["add(999999, 1)"],
            "workspace": str(ws),
        },
    )
    data = parse_tool_result(result)
    assert "error" not in data, f"submit_adversarial_report failed: {data}"

    # 5. Write tests to disk
    result = await client.call_tool("crucis_write_tests", {"workspace": str(ws)})
    data = parse_tool_result(result)
    assert len(data.get("written", [])) > 0

    # 6. Verify implementation (tests + holdout evals)
    result = await client.call_tool(
        "crucis_verify_implementation", {"workspace": str(ws)}
    )
    data = parse_tool_result(result)
    assert data.get("tests_passed") is True, f"tests failed: {data}"
    assert data.get("holdout_passed") is True, f"holdout failed: {data}"
    assert data.get("overall") is True, f"verify_implementation failed: {data}"
    assert data.get("holdout_total", 0) > 0, "holdout evals should have run"

    # 7. Summary reflects final state
    result = await client.call_tool("crucis_summary", {"workspace": str(ws)})
    data = parse_tool_result(result)
    assert data.get("found") is True
    assert len(data.get("tasks", [])) == 1
    assert data["tasks"][0]["status"] in ("complete", "adversarially_reviewed")


@pytest.mark.asyncio
async def test_error_envelope_consistency(mcp_client):
    """Verify all error responses include error + error_type fields.

    Args:
        mcp_client: In-memory MCP client fixture.
    """
    client, ws = mcp_client

    # Summary before any checkpoint exists
    result = await client.call_tool("crucis_summary", {"workspace": str(ws)})
    data = parse_tool_result(result)
    _assert_error_envelope(data)
    assert data.get("found") is False

    # Write tests before any checkpoint
    result = await client.call_tool("crucis_write_tests", {"workspace": str(ws)})
    data = parse_tool_result(result)
    _assert_error_envelope(data)

    # Verify before any checkpoint
    result = await client.call_tool(
        "crucis_verify_implementation", {"workspace": str(ws)}
    )
    data = parse_tool_result(result)
    _assert_error_envelope(data)

    # Get adversary prompt before any checkpoint
    result = await client.call_tool(
        "crucis_get_prompt",
        {"step": "adversary", "task_name": "add", "workspace": str(ws)},
    )
    data = parse_tool_result(result)
    _assert_error_envelope(data)

    # Invalid step name
    result = await client.call_tool(
        "crucis_get_prompt",
        {"step": "invalid", "workspace": str(ws)},
    )
    data = parse_tool_result(result)
    _assert_error_envelope(data)

    # Submit adversarial report before any checkpoint
    result = await client.call_tool(
        "crucis_submit_adversarial_report",
        {
            "task_name": "add",
            "attack_vectors": ["test"],
            "generalization_gaps": ["test"],
            "suggested_probe_tests": ["test"],
            "workspace": str(ws),
        },
    )
    data = parse_tool_result(result)
    _assert_error_envelope(data)

    # Submit test suite with invalid syntax
    result = await client.call_tool(
        "crucis_submit_test_suite",
        {"task_name": "add", "test_source": "def broken(", "workspace": str(ws)},
    )
    data = parse_tool_result(result)
    _assert_error_envelope(data)
    assert data.get("accepted") is False
    assert data.get("syntax_valid") is False
