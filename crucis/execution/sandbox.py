"""Docker subprocess wrapper for isolated pytest execution."""

import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from crucis.execution.constants import DOCKER_CHECK_TIMEOUT_SEC, DOCKER_PYTEST_TIMEOUT_SEC


@dataclass
class DockerTestResult:
    """Result from running pytest inside a Docker container.

    Attributes:
        passed: True when all tests passed.
        exit_code: Docker/pytest process exit code.
        stdout: Standard output from the container.
        stderr: Standard error from the container.
        failing_tests: Extracted list of failing test descriptions.
    """

    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    failing_tests: list[str] = field(default_factory=list)


def check_docker_available() -> bool:
    """Check whether Docker is installed and the daemon is running.

    Returns:
        True when ``docker info`` exits successfully.
    """
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=DOCKER_CHECK_TIMEOUT_SEC,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def build_docker_pytest_command(
    workspace: Path,
    python_version: str = "3.12",
    test_targets: list[str] | None = None,
) -> list[str]:
    """Construct the Docker CLI command to run pytest in a container.

    Args:
        workspace: Host directory to mount as ``/app`` inside the container.
        python_version: Python image tag version.
        test_targets: Optional pytest targets relative to ``/app``.

    Returns:
        List of command arguments for ``subprocess.run``.
    """
    targets = test_targets or ["tests/"]
    pytest_targets = " ".join(shlex.quote(target) for target in targets)
    return [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{workspace.resolve()}:/app",
        "-w",
        "/app",
        f"python:{python_version}-slim",
        "sh",
        "-c",
        f"pip install -q . && pip install -q pytest && pytest {pytest_targets} -v",
    ]


def run_pytest_in_docker(
    workspace: Path,
    timeout: int = DOCKER_PYTEST_TIMEOUT_SEC,
    python_version: str = "3.12",
    test_targets: list[str] | None = None,
) -> DockerTestResult:
    """Run pytest inside a Docker container and return the result.

    Args:
        workspace: Host directory containing tests and implementation.
        timeout: Maximum seconds before the container is killed.
        python_version: Python image tag version.
        test_targets: Optional pytest targets relative to ``/app``.

    Returns:
        DockerTestResult with pass/fail status and captured output.
    """
    cmd = build_docker_pytest_command(workspace, python_version, test_targets)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return DockerTestResult(
            passed=False,
            exit_code=-1,
            stdout="",
            stderr=f"Docker pytest timed out after {timeout}s",
        )
    except FileNotFoundError:
        return DockerTestResult(
            passed=False,
            exit_code=-1,
            stdout="",
            stderr="Docker binary not found",
        )
    return DockerTestResult(
        passed=result.returncode == 0,
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        failing_tests=parse_pytest_failures(result.stdout),
    )


def parse_pytest_failures(output: str) -> list[str]:
    """Extract failing test descriptions from pytest verbose output.

    Args:
        output: Raw stdout from a pytest run.

    Returns:
        List of failure description strings.
    """
    failures = []
    for line in output.splitlines():
        if re.match(r"^FAILED\s+", line):
            failures.append(line.strip())
    return failures
