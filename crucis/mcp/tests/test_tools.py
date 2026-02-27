"""Tests for Crucis MCP server tools via in-memory client."""

from __future__ import annotations

import textwrap

import pytest

from crucis.mcp.tests.conftest import parse_tool_result

pytestmark = pytest.mark.timeout(30)


class TestCrucisInit:
    """Tests for crucis_init tool."""

    async def test_init_scaffolds_workspace(self, mcp_client):
        """Init should create starter files in a fresh workspace.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        fresh = ws / "subdir"
        fresh.mkdir()
        (fresh / ".crucis").mkdir()
        result = await client.call_tool(
            "crucis_init", {"name": "test_proj", "workspace": str(fresh)}
        )
        data = parse_tool_result(result)
        assert "error" not in data
        assert data["workspace"].endswith("subdir")
        assert any("objective.yaml" in p for p in data["created"])

    async def test_init_skips_existing_files(self, mcp_client):
        """Init should not overwrite files that already exist.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        # objective.yaml already exists from fixture
        result = await client.call_tool(
            "crucis_init", {"name": "test_proj", "workspace": str(ws)}
        )
        data = parse_tool_result(result)
        assert "error" not in data
        # Should not have recreated objective.yaml
        assert not any("objective.yaml" in p for p in data["created"])


class TestCrucisDryRun:
    """Tests for crucis_dry_run tool."""

    async def test_dry_run_returns_task_preview(self, mcp_client):
        """Dry run should return task names and status.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        result = await client.call_tool("crucis_dry_run", {"workspace": str(ws)})
        data = parse_tool_result(result)
        assert data["dry_run"] is True
        assert data["objective_name"] == "add"
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["task_name"] == "add"
        assert data["tasks"][0]["current_status"] == "pending"

    async def test_dry_run_missing_objective(self, mcp_client):
        """Dry run should return error when objective.yaml is missing.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        (ws / "objective.yaml").unlink()
        result = await client.call_tool("crucis_dry_run", {"workspace": str(ws)})
        data = parse_tool_result(result)
        assert "error" in data


class TestCrucisReset:
    """Tests for crucis_reset tool."""

    async def test_reset_all_no_checkpoint(self, mcp_client):
        """Reset all should succeed even without an existing checkpoint.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        result = await client.call_tool("crucis_reset", {"workspace": str(ws)})
        data = parse_tool_result(result)
        assert data["reset"] == "all"

    async def test_reset_specific_task(self, mcp_client):
        """Reset specific task should clear only that task's progress.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        # First submit a test suite to create a checkpoint
        test_src = textwrap.dedent("""\
            def test_add():
                assert 1 + 2 == 3
        """)
        await client.call_tool(
            "crucis_submit_test_suite",
            {"task_name": "add", "test_source": test_src, "workspace": str(ws)},
        )
        # Now reset it
        result = await client.call_tool(
            "crucis_reset", {"task_names": ["add"], "workspace": str(ws)}
        )
        data = parse_tool_result(result)
        assert "add" in data["reset"]


class TestCrucisValidate:
    """Tests for crucis_validate tool."""

    async def test_validate_valid_objective(self, mcp_client):
        """Validate should return valid=True for a well-formed objective.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        result = await client.call_tool("crucis_validate", {"workspace": str(ws)})
        data = parse_tool_result(result)
        assert data["valid"] is True
        assert data["name"] == "add"

    async def test_validate_invalid_yaml(self, mcp_client):
        """Validate should return valid=False for malformed YAML.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        (ws / "objective.yaml").write_text("not: [valid: yaml: here", encoding="utf-8")
        result = await client.call_tool("crucis_validate", {"workspace": str(ws)})
        data = parse_tool_result(result)
        assert data["valid"] is False


class TestCrucisSummary:
    """Tests for crucis_summary tool."""

    async def test_summary_no_checkpoint(self, mcp_client):
        """Summary should return found=False without a checkpoint.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        result = await client.call_tool("crucis_summary", {"workspace": str(ws)})
        data = parse_tool_result(result)
        assert data["found"] is False

    async def test_summary_with_checkpoint(self, mcp_client):
        """Summary should return task status after submitting a test suite.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        test_src = "def test_add():\n    assert 1 + 2 == 3\n"
        await client.call_tool(
            "crucis_submit_test_suite",
            {"task_name": "add", "test_source": test_src, "workspace": str(ws)},
        )
        result = await client.call_tool("crucis_summary", {"workspace": str(ws)})
        data = parse_tool_result(result)
        assert data["found"] is True
        assert data["summary"]["total_tasks"] == 1

    async def test_summary_specific_task(self, mcp_client):
        """Summary with task_name should return detail for that task.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        test_src = "def test_add():\n    assert 1 + 2 == 3\n"
        await client.call_tool(
            "crucis_submit_test_suite",
            {"task_name": "add", "test_source": test_src, "workspace": str(ws)},
        )
        result = await client.call_tool(
            "crucis_summary", {"task_name": "add", "workspace": str(ws)}
        )
        data = parse_tool_result(result)
        assert data["found"] is True
        assert data["name"] == "add"
        assert data["status"] == "train_suite_approved"


class TestCrucisDoctor:
    """Tests for crucis_doctor tool."""

    async def test_doctor_returns_report(self, mcp_client):
        """Doctor should return a diagnostics report.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        result = await client.call_tool("crucis_doctor", {"workspace": str(ws)})
        data = parse_tool_result(result)
        # Doctor returns either checks or an error
        assert "checks" in data or "error" in data


class TestCrucisCheckConstraints:
    """Tests for crucis_check_constraints tool."""

    async def test_check_constraints_passes(self, mcp_client):
        """Check constraints should pass for simple source code.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        result = await client.call_tool(
            "crucis_check_constraints",
            {"source_code": "def test_x():\n    assert True\n", "workspace": str(ws)},
        )
        data = parse_tool_result(result)
        assert "primary" in data
        assert data["primary"]["passed"] is True

    async def test_check_constraints_rejects_oversized(self, mcp_client):
        """Check constraints should reject source exceeding 1 MB.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        big_source = "x = 1\n" * 200_000  # ~1.2 MB
        result = await client.call_tool(
            "crucis_check_constraints",
            {"source_code": big_source, "workspace": str(ws)},
        )
        data = parse_tool_result(result)
        assert "error" in data


class TestCrucisGetPrompt:
    """Tests for crucis_get_prompt tool."""

    async def test_get_prompt_generation(self, mcp_client):
        """Get prompt for generation step should return a system prompt.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        result = await client.call_tool(
            "crucis_get_prompt",
            {"step": "generation", "task_name": "add", "workspace": str(ws)},
        )
        data = parse_tool_result(result)
        assert data["step"] == "generation"
        assert "prompt" in data
        assert len(data["prompt"]) > 0

    async def test_get_prompt_invalid_step(self, mcp_client):
        """Get prompt should error on invalid step name.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        result = await client.call_tool(
            "crucis_get_prompt",
            {"step": "nonexistent", "workspace": str(ws)},
        )
        data = parse_tool_result(result)
        assert "error" in data

    async def test_get_prompt_adversary(self, mcp_client):
        """Get prompt for adversary step should work after submitting tests.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        test_src = "def test_add():\n    assert 1 + 2 == 3\n"
        await client.call_tool(
            "crucis_submit_test_suite",
            {"task_name": "add", "test_source": test_src, "workspace": str(ws)},
        )
        result = await client.call_tool(
            "crucis_get_prompt",
            {"step": "adversary", "task_name": "add", "workspace": str(ws)},
        )
        data = parse_tool_result(result)
        assert data["step"] == "adversary"
        assert "prompt" in data


class TestCrucisSubmitTestSuite:
    """Tests for crucis_submit_test_suite tool."""

    async def test_submit_valid_suite(self, mcp_client):
        """Submit should accept syntactically valid test source.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        test_src = "def test_add():\n    assert 1 + 2 == 3\n"
        result = await client.call_tool(
            "crucis_submit_test_suite",
            {"task_name": "add", "test_source": test_src, "workspace": str(ws)},
        )
        data = parse_tool_result(result)
        assert data["accepted"] is True
        assert data["syntax_valid"] is True
        assert data["task_status"] == "train_suite_approved"

    async def test_submit_invalid_syntax(self, mcp_client):
        """Submit should reject source with syntax errors.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        result = await client.call_tool(
            "crucis_submit_test_suite",
            {"task_name": "add", "test_source": "def broken(", "workspace": str(ws)},
        )
        data = parse_tool_result(result)
        assert data["accepted"] is False
        assert data["syntax_valid"] is False


class TestCrucisSubmitAdversarialReport:
    """Tests for crucis_submit_adversarial_report tool."""

    async def test_submit_report_after_suite(self, mcp_client):
        """Submit adversarial report should succeed after submitting tests.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        test_src = "def test_add():\n    assert 1 + 2 == 3\n"
        await client.call_tool(
            "crucis_submit_test_suite",
            {"task_name": "add", "test_source": test_src, "workspace": str(ws)},
        )
        result = await client.call_tool(
            "crucis_submit_adversarial_report",
            {
                "task_name": "add",
                "attack_vectors": ["hardcoded return"],
                "generalization_gaps": ["no negative numbers"],
                "suggested_probe_tests": ["test_add(-1, -2)"],
                "workspace": str(ws),
            },
        )
        data = parse_tool_result(result)
        assert data["accepted"] is True
        assert data["task_status"] == "adversarially_reviewed"

    async def test_submit_report_no_checkpoint(self, mcp_client):
        """Submit report should error without an existing checkpoint.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        result = await client.call_tool(
            "crucis_submit_adversarial_report",
            {
                "task_name": "add",
                "attack_vectors": [],
                "generalization_gaps": [],
                "suggested_probe_tests": [],
                "workspace": str(ws),
            },
        )
        data = parse_tool_result(result)
        assert "error" in data


class TestCrucisWriteTests:
    """Tests for crucis_write_tests tool."""

    async def test_write_tests_creates_files(self, mcp_client):
        """Write tests should materialize test files from checkpoint.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        test_src = "def test_add():\n    assert 1 + 2 == 3\n"
        await client.call_tool(
            "crucis_submit_test_suite",
            {"task_name": "add", "test_source": test_src, "workspace": str(ws)},
        )
        result = await client.call_tool(
            "crucis_write_tests", {"workspace": str(ws)}
        )
        data = parse_tool_result(result)
        assert data["test_count"] >= 1
        assert any("test_add.py" in p for p in data["written"])

    async def test_write_tests_no_checkpoint(self, mcp_client):
        """Write tests should error without a checkpoint.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        result = await client.call_tool(
            "crucis_write_tests", {"workspace": str(ws)}
        )
        data = parse_tool_result(result)
        assert "error" in data


class TestCrucisVerifyImplementation:
    """Tests for crucis_verify_implementation tool."""

    async def test_verify_passes_with_correct_impl(self, mcp_client):
        """Verify should pass when implementation satisfies tests and holdouts.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        test_src = textwrap.dedent("""\
            from src.solution import add

            def test_add_basic():
                assert add(1, 2) == 3
        """)
        await client.call_tool(
            "crucis_submit_test_suite",
            {"task_name": "add", "test_source": test_src, "workspace": str(ws)},
        )
        await client.call_tool("crucis_write_tests", {"workspace": str(ws)})
        result = await client.call_tool(
            "crucis_verify_implementation", {"workspace": str(ws)}
        )
        data = parse_tool_result(result)
        assert data["tests_passed"] is True

    async def test_verify_requires_write_tests_first(self, mcp_client):
        """Verify should error when tests haven't been written to disk.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, ws = mcp_client
        test_src = "def test_add():\n    assert 1 + 2 == 3\n"
        await client.call_tool(
            "crucis_submit_test_suite",
            {"task_name": "add", "test_source": test_src, "workspace": str(ws)},
        )
        result = await client.call_tool(
            "crucis_verify_implementation", {"workspace": str(ws)}
        )
        data = parse_tool_result(result)
        assert "error" in data
        assert "write_tests" in data.get("hint", "").lower()


class TestListTools:
    """Tests for tool listing."""

    async def test_lists_all_12_tools(self, mcp_client):
        """Server should expose exactly 12 tools.

        Args:
            mcp_client: In-memory MCP client fixture.
        """
        client, _ = mcp_client
        tools = await client.list_tools()
        tool_names = [t.name for t in tools.tools]
        expected = {
            "crucis_init",
            "crucis_run",
            "crucis_run_fit",
            "crucis_run_evaluate",
            "crucis_run_plan",
            "crucis_dry_run",
            "crucis_reset",
            "crucis_validate",
            "crucis_summary",
            "crucis_doctor",
            "crucis_promote",
            "crucis_optimizer_worker",
            "crucis_check_constraints",
            "crucis_get_prompt",
            "crucis_submit_test_suite",
            "crucis_submit_adversarial_report",
            "crucis_run_probe",
            "crucis_write_tests",
            "crucis_verify_implementation",
        }
        assert len(tool_names) == len(expected)
        assert set(tool_names) == expected
