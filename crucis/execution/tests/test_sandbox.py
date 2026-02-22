"""Tests for the Docker sandbox module."""

import subprocess
from unittest.mock import patch

from crucis.execution.sandbox import (
    DockerTestResult,
    build_docker_pytest_command,
    check_docker_available,
    parse_pytest_failures,
    run_pytest_in_docker,
)

# --- check_docker_available ---


class TestCheckDockerAvailable:
    """Tests for check_docker_available."""

    @patch("crucis.execution.sandbox.subprocess.run")
    def test_docker_available(self, mock_run):
        """Test that check_docker_available returns True when Docker is running.

        Args:
            mock_run: Mocked subprocess.run.
        """
        mock_run.return_value = type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        assert check_docker_available() is True

    @patch("crucis.execution.sandbox.subprocess.run")
    def test_docker_not_available(self, mock_run):
        """Test that check_docker_available returns False when Docker is not running.

        Args:
            mock_run: Mocked subprocess.run.
        """
        mock_run.return_value = type(
            "Result", (), {"returncode": 1, "stdout": "", "stderr": "error"}
        )()
        assert check_docker_available() is False

    @patch("crucis.execution.sandbox.subprocess.run", side_effect=FileNotFoundError)
    def test_docker_binary_missing(self, mock_run):
        """Test that check_docker_available returns False when docker is not installed.

        Args:
            mock_run: Mocked subprocess.run raising FileNotFoundError.
        """
        assert check_docker_available() is False

    @patch(
        "crucis.execution.sandbox.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=10),
    )
    def test_docker_timeout(self, mock_run):
        """Test that check_docker_available returns False on timeout.

        Args:
            mock_run: Mocked subprocess.run raising TimeoutExpired.
        """
        assert check_docker_available() is False


# --- build_docker_pytest_command ---


class TestBuildDockerPytestCommand:
    """Tests for build_docker_pytest_command."""

    def test_command_structure(self, tmp_path):
        """Test that the command has the correct Docker structure.

        Args:
            tmp_path: Pytest tmp_path fixture.
        """
        cmd = build_docker_pytest_command(tmp_path)
        assert cmd[0] == "docker"
        assert cmd[1] == "run"
        assert "--rm" in cmd
        assert "-w" in cmd
        assert "/app" in cmd

    def test_workspace_mount(self, tmp_path):
        """Test that the workspace is mounted as a volume.

        Args:
            tmp_path: Pytest tmp_path fixture.
        """
        cmd = build_docker_pytest_command(tmp_path)
        volume_arg = cmd[cmd.index("-v") + 1]
        assert str(tmp_path.resolve()) in volume_arg
        assert ":/app" in volume_arg

    def test_default_python_version(self, tmp_path):
        """Test that the default Python version is 3.12.

        Args:
            tmp_path: Pytest tmp_path fixture.
        """
        cmd = build_docker_pytest_command(tmp_path)
        assert "python:3.12-slim" in cmd

    def test_custom_python_version(self, tmp_path):
        """Test that a custom Python version is used.

        Args:
            tmp_path: Pytest tmp_path fixture.
        """
        cmd = build_docker_pytest_command(tmp_path, python_version="3.11")
        assert "python:3.11-slim" in cmd

    def test_installs_pytest_and_runs(self, tmp_path):
        """Test that the command installs pytest and runs it.

        Args:
            tmp_path: Pytest tmp_path fixture.
        """
        cmd = build_docker_pytest_command(tmp_path)
        shell_cmd = cmd[-1]
        assert "pip install -q ." in shell_cmd
        assert "pip install -q pytest" in shell_cmd
        assert "pytest tests/ -v" in shell_cmd

    def test_supports_custom_test_targets(self, tmp_path):
        """Test that custom pytest targets are added to the docker command.

        Args:
            tmp_path: Temporary directory provided by pytest.
        """
        cmd = build_docker_pytest_command(
            tmp_path, test_targets=["tests/", ".atdd_hidden_eval_123"]
        )
        shell_cmd = cmd[-1]
        assert "pip install -q ." in shell_cmd
        assert "pytest tests/ .atdd_hidden_eval_123 -v" in shell_cmd


# --- run_pytest_in_docker ---


class TestRunPytestInDocker:
    """Tests for run_pytest_in_docker."""

    @patch("crucis.execution.sandbox.subprocess.run")
    def test_passing_tests(self, mock_run, tmp_path):
        """Test that passing tests return DockerTestResult with passed=True.

        Args:
            mock_run: Mocked subprocess.run.
            tmp_path: Pytest tmp_path fixture.
        """
        mock_run.return_value = type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": "test_add.py::test_basic PASSED\n1 passed",
                "stderr": "",
            },
        )()
        result = run_pytest_in_docker(tmp_path)
        assert isinstance(result, DockerTestResult)
        assert result.passed is True
        assert result.exit_code == 0

    @patch("crucis.execution.sandbox.subprocess.run")
    def test_failing_tests(self, mock_run, tmp_path):
        """Test that failing tests return DockerTestResult with passed=False.

        Args:
            mock_run: Mocked subprocess.run.
            tmp_path: Pytest tmp_path fixture.
        """
        mock_run.return_value = type(
            "Result",
            (),
            {
                "returncode": 1,
                "stdout": "FAILED tests/test_add.py::test_basic - assert 0 == 3\n1 failed",
                "stderr": "",
            },
        )()
        result = run_pytest_in_docker(tmp_path)
        assert result.passed is False
        assert result.exit_code == 1
        assert len(result.failing_tests) == 1

    @patch("crucis.execution.sandbox.subprocess.run")
    def test_forwards_custom_targets(self, mock_run, tmp_path):
        """Test that run_pytest_in_docker forwards custom targets.

        Args:
            mock_run: Mock object for `run` interactions.
            tmp_path: Temporary directory provided by pytest.
        """
        mock_run.return_value = type(
            "Result", (), {"returncode": 0, "stdout": "1 passed", "stderr": ""}
        )()
        run_pytest_in_docker(tmp_path, test_targets=["tests/", ".hidden_tests"])
        cmd = mock_run.call_args[0][0]
        assert "pytest tests/ .hidden_tests -v" in cmd[-1]

    @patch(
        "crucis.execution.sandbox.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=120),
    )
    def test_timeout(self, mock_run, tmp_path):
        """Test that timeout returns a failed DockerTestResult.

        Args:
            mock_run: Mocked subprocess.run raising TimeoutExpired.
            tmp_path: Pytest tmp_path fixture.
        """
        result = run_pytest_in_docker(tmp_path)
        assert result.passed is False
        assert result.exit_code == -1
        assert "timed out" in result.stderr

    @patch("crucis.execution.sandbox.subprocess.run", side_effect=FileNotFoundError)
    def test_docker_not_found(self, mock_run, tmp_path):
        """Test that missing Docker binary returns a failed DockerTestResult.

        Args:
            mock_run: Mocked subprocess.run raising FileNotFoundError.
            tmp_path: Pytest tmp_path fixture.
        """
        result = run_pytest_in_docker(tmp_path)
        assert result.passed is False
        assert result.exit_code == -1
        assert "not found" in result.stderr


# --- parse_pytest_failures ---


class TestParsePytestFailures:
    """Tests for parse_pytest_failures."""

    def test_extracts_failures(self):
        """Test that FAILED lines are extracted from pytest output."""
        output = (
            "tests/test_add.py::test_basic PASSED\n"
            "FAILED tests/test_add.py::test_negative - AssertionError\n"
            "FAILED tests/test_add.py::test_zero - assert 0 != 0\n"
            "2 failed, 1 passed\n"
        )
        failures = parse_pytest_failures(output)
        assert len(failures) == 2
        assert "test_negative" in failures[0]
        assert "test_zero" in failures[1]

    def test_all_passing(self):
        """Test that all-passing output returns empty list."""
        output = "tests/test_add.py::test_basic PASSED\n1 passed\n"
        assert parse_pytest_failures(output) == []

    def test_empty_output(self):
        """Test that empty output returns empty list."""
        assert parse_pytest_failures("") == []
