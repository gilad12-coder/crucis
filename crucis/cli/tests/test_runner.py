import json
import os
import shutil
import subprocess as sp
from unittest.mock import patch

import pytest

from crucis.cli.runner import (
    build_command,
    build_implementation_command,
    parse_cli_output,
    run_cli_agent,
)
from crucis.models import CLIResult

# --- Unit tests: command construction ---


class TestBuildCommand:
    """Tests for build_command."""

    def test_build_command_claude_agent(self):
        """Test that build_command produces a valid claude CLI command."""
        cmd = build_command(
            prompt="Write hello world",
            agent="claude",
            model="sonnet",
            budget=5.0,
        )
        assert isinstance(cmd, list)
        assert "claude" in cmd[0]
        assert "-p" in cmd
        assert "--output-format" in cmd
        prompt_idx = cmd.index("-p") + 1
        assert "Write hello world" in cmd[prompt_idx]

    def test_build_command_codex_agent(self):
        """Test that build_command produces a valid codex CLI command."""
        cmd = build_command(
            prompt="Write hello world",
            agent="codex",
            model="gpt-5.2-codex",
            budget=5.0,
        )
        assert "codex" in cmd[0]
        assert "--model" in cmd

    def test_build_command_includes_budget(self):
        """Test that build_command includes the budget in the command."""
        cmd = build_command(prompt="test", agent="claude", model="sonnet", budget=3.50)
        cmd_str = " ".join(cmd)
        assert "3.5" in cmd_str

    def test_build_command_includes_model(self):
        """Test that build_command includes the model in the command."""
        cmd = build_command(prompt="test", agent="claude", model="haiku", budget=5.0)
        cmd_str = " ".join(cmd)
        assert "haiku" in cmd_str

    def test_build_command_includes_tool_restrictions(self):
        """Test that build_command includes tool restriction flags."""
        cmd = build_command(prompt="test", agent="claude", model="sonnet", budget=5.0)
        cmd_str = " ".join(cmd)
        assert "allowedTools" in cmd_str or "disallowedTools" in cmd_str


class TestBuildImplementationCommand:
    """Tests for build_implementation_command."""

    def test_build_implementation_command_codex(self):
        """Test that build_implementation_command produces a valid codex command."""
        cmd = build_implementation_command(
            prompt="Make all tests pass",
            agent="codex",
            model="o4-mini",
        )
        assert "codex" in cmd[0]
        assert "exec" in cmd
        assert "--full-auto" in cmd
        assert "Make all tests pass" in cmd

    def test_build_implementation_command_claude(self):
        """Test that build_implementation_command produces a valid claude command."""
        cmd = build_implementation_command(
            prompt="Make all tests pass",
            agent="claude",
            model="sonnet",
        )
        assert "claude" in cmd[0]
        assert "-p" in cmd
        assert "Make all tests pass" in cmd


# --- Unit tests: output parsing ---


class TestParseCliOutput:
    """Tests for parse_cli_output."""

    def test_parse_cli_output_json(self):
        """Test that parse_cli_output parses valid JSON stdout."""
        stdout = json.dumps({"result": "success", "tests": ["test_1", "test_2"]})
        result = parse_cli_output(stdout=stdout, stderr="", exit_code=0)
        assert isinstance(result, CLIResult)
        assert result.parsed_json is not None
        assert result.parsed_json["result"] == "success"

    def test_parse_cli_output_non_json(self):
        """Test that parse_cli_output handles plain text output."""
        result = parse_cli_output(stdout="Just plain text output", stderr="", exit_code=0)
        assert result.parsed_json is None
        assert result.stdout == "Just plain text output"

    def test_parse_cli_output_preserves_exit_code(self):
        """Test that parse_cli_output preserves the original exit code."""
        success = parse_cli_output(stdout="ok", stderr="", exit_code=0)
        assert success.exit_code == 0

        failure = parse_cli_output(stdout="", stderr="error", exit_code=1)
        assert failure.exit_code == 1

    def test_parse_cli_output_json_with_surrounding_text(self):
        """Test that parse_cli_output handles JSON embedded in surrounding text."""
        # CLI might output text before/after JSON
        stdout = 'Some preamble\n{"result": "ok"}\nSome epilogue'
        result = parse_cli_output(stdout=stdout, stderr="", exit_code=0)
        # Should still try to extract JSON
        assert result.stdout == stdout


# --- Error handling ---


class TestRunCliAgentErrorHandling:
    """Tests for run_cli_agent error handling."""

    @patch("crucis.cli.runner.subprocess.run")
    def test_run_cli_agent_timeout_returns_error_result(self, mock_run):
        """Test that run_cli_agent returns an error result on timeout.

        Args:
            mock_run: Mocked subprocess.run.
        """
        mock_run.side_effect = sp.TimeoutExpired(cmd=["claude"], timeout=300)
        result = run_cli_agent(prompt="test", agent="claude", model="sonnet", budget=1.0)
        assert result.exit_code == -1
        assert "timeout" in result.stderr.lower()

    @patch("crucis.cli.runner.subprocess.run")
    def test_run_cli_agent_missing_binary_returns_error_result(self, mock_run):
        """Test that run_cli_agent returns an error result when binary is missing.

        Args:
            mock_run: Mocked subprocess.run.
        """
        mock_run.side_effect = FileNotFoundError("No such file")
        result = run_cli_agent(prompt="test", agent="claude", model="sonnet", budget=1.0)
        assert result.exit_code == -1
        assert "not found" in result.stderr.lower()


# --- Smoke tests: verify CLIs are callable ---


class TestCliSmoke:
    """Smoke tests for CLI binary availability."""

    @pytest.mark.llm
    @pytest.mark.parametrize(
        ("agent", "model"),
        [
            pytest.param("claude", "sonnet", id="claude"),
            pytest.param("codex", "gpt-5.2-codex", id="codex"),
        ],
    )
    def test_agent_returns_output(self, agent: str, model: str):
        """Test that a CLI agent returns valid output.

        Args:
            agent: CLI agent name to invoke.
            model: Model identifier for the agent.
        """
        if shutil.which(agent) is None:
            pytest.skip(f"requires {agent} CLI")
        if os.environ.get("CLAUDECODE") is not None:
            pytest.skip("cannot run inside a nested agent session")

        result = run_cli_agent(
            prompt="Respond with exactly: hello",
            agent=agent,
            model=model,
            budget=1.0,
        )
        assert isinstance(result, CLIResult)
        assert result.exit_code == 0
        assert len(result.stdout) > 0
