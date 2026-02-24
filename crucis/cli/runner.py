"""Subprocess wrapper for running Claude Code and Codex CLIs."""

import contextlib
import json
import os
import re
import subprocess
import sys

from pathlib import Path

from crucis.cli.constants import CLI_AGENT_TIMEOUT_SEC, INTERACTIVE_AGENT_TIMEOUT_SEC
from crucis.display import display_agent_boundary
from crucis.models import CLIResult

_AGENT_CLAUDE = "claude"
_AGENT_CODEX = "codex"
_MODEL_FLAG = "--model"
_ALLOWED_TOOLS_FLAG = "--allowedTools"
_SKIP_GIT_REPO_CHECK_FLAG = "--skip-git-repo-check"
_RATE_LIMIT_RE = re.compile(
    r"usage limit|rate.?limit|Too Many Requests|error code:\s*429",
    re.IGNORECASE,
)
_NON_TRANSIENT_RE = re.compile(
    r"not inside a trusted directory"
    r"|cannot be launched inside another"
    r"|CLAUDECODE"
    r"|model.+is not supported"
    r"|not supported when using Codex"
    r"|invalid_model"
    r"|does not exist",
    re.IGNORECASE,
)
_CODEX_JSON_DETAIL_RE = re.compile(r'\{"detail"\s*:\s*"([^"]+)"\}')
_ISO_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T")
_CODEX_NOISE_PREFIXES = (
    "mcp:",
    "OpenAI Codex",
    "--------",
    "workdir:",
    "model:",
    "provider:",
    "approval:",
    "sandbox:",
    "reasoning",
    "session id:",
    "user",
)

_NESTING_ENV_VARS = ("CLAUDECODE",)
"""Environment variables stripped from child agent processes to avoid nesting errors."""


def _clean_agent_env() -> dict[str, str]:
    """Build a subprocess environment with nesting-related vars removed.

    Returns:
        Copy of os.environ without nesting-problematic variables.
    """
    env = os.environ.copy()
    for var in _NESTING_ENV_VARS:
        env.pop(var, None)
    return env


def build_command(prompt: str, agent: str, model: str, budget: float) -> list[str]:
    """Construct a CLI command as a list of strings.

    Args:
        prompt: Prompt text for the agent.
        agent: Agent name (claude or codex).
        model: Model name to use.
        budget: Budget or max turns value.

    Returns:
        List of command arguments.
    """
    if agent == _AGENT_CLAUDE:
        return [
            _AGENT_CLAUDE,
            "-p",
            prompt,
            "--output-format",
            "json",
            _MODEL_FLAG,
            model,
            "--max-budget-usd",
            str(budget),
            _ALLOWED_TOOLS_FLAG,
            "",
        ]
    elif agent == _AGENT_CODEX:
        cmd = [_AGENT_CODEX, "exec", _SKIP_GIT_REPO_CHECK_FLAG]
        if model:
            cmd.extend([_MODEL_FLAG, model])
        cmd.append(prompt)
        return cmd
    else:
        raise ValueError(f"Unknown agent: {agent}")


def build_implementation_command(prompt: str, agent: str, model: str) -> list[str]:
    """Build a CLI command for implementation-phase code changes.

    Args:
        prompt: Prompt text for the implementation agent.
        agent: Agent name (claude or codex).
        model: Model name to use.

    Returns:
        List of command arguments.
    """
    if agent == _AGENT_CODEX:
        cmd = [_AGENT_CODEX, "exec", _SKIP_GIT_REPO_CHECK_FLAG, "--full-auto"]
        if model:
            cmd.extend(["-m", model])
        cmd.append(prompt)
        return cmd
    if agent == _AGENT_CLAUDE:
        return [
            _AGENT_CLAUDE,
            "-p",
            prompt,
            _MODEL_FLAG,
            model,
            _ALLOWED_TOOLS_FLAG,
            "Edit,Write,Read,Bash",
        ]
    raise ValueError(f"Unknown agent: {agent}")


def is_rate_limited(stderr: str) -> bool:
    """Check whether stderr contains a rate-limit error.

    Args:
        stderr: Standard error output from the agent subprocess.

    Returns:
        True when the output contains a rate-limit indicator.
    """
    return bool(_RATE_LIMIT_RE.search(stderr))


def extract_rate_limit_detail(stderr: str) -> str:
    """Extract only the provider's rate-limit message from stderr.

    Args:
        stderr: Raw standard error output from the agent subprocess.

    Returns:
        The line containing the rate-limit indicator, trimmed to 200 chars.
    """
    for line in stderr.splitlines():
        if _RATE_LIMIT_RE.search(line):
            return line.strip()[:200]
    return ""


def is_non_transient_error(stderr: str) -> bool:
    """Check whether stderr contains an error that will never self-resolve.

    Args:
        stderr: Standard error output from the agent subprocess.

    Returns:
        True when the output indicates a non-transient failure.
    """
    return bool(_NON_TRANSIENT_RE.search(stderr))


def extract_concise_error(stderr: str) -> str:
    """Extract an actionable error message from noisy agent stderr.

    Args:
        stderr: Raw standard error output from the agent subprocess.

    Returns:
        Concise error string, or the original stderr if no extraction matched.
    """
    match = _CODEX_JSON_DETAIL_RE.search(stderr)
    if match:
        return match.group(1)
    lines = [
        line
        for line in stderr.splitlines()
        if line.strip()
        and not line.lstrip().startswith(_CODEX_NOISE_PREFIXES)
        and not _ISO_TIMESTAMP_RE.match(line.lstrip())
    ]
    if lines:
        return "\n".join(lines[-5:])
    return stderr.strip()[-500:] if stderr.strip() else ""


def parse_cli_output(stdout: str, stderr: str, exit_code: int) -> CLIResult:
    """Parse raw subprocess output into a CLIResult.

    Args:
        stdout: Standard output from subprocess.
        stderr: Standard error from subprocess.
        exit_code: Process exit code.

    Returns:
        CLIResult with parsed output. When the output is Claude JSON format,
        the result text is extracted into stdout for downstream processing.
    """
    parsed_json = None
    with contextlib.suppress(json.JSONDecodeError, ValueError):
        parsed_json = json.loads(stdout)

    effective_stdout = stdout
    if parsed_json and isinstance(parsed_json, dict) and "result" in parsed_json:
        effective_stdout = parsed_json["result"]

    return CLIResult(
        stdout=effective_stdout,
        stderr=stderr,
        exit_code=exit_code,
        parsed_json=parsed_json,
    )


def run_cli_agent(
    prompt: str, agent: str, model: str, budget: float, timeout: int = CLI_AGENT_TIMEOUT_SEC
) -> CLIResult:
    """Run a CLI agent subprocess and return the result.

    Stderr streams to the terminal in real time so the user sees agent
    progress. Stdout is captured for response parsing.

    Args:
        prompt: Prompt text for the agent.
        agent: Agent name (claude or codex).
        model: Model name to use.
        budget: Budget or max turns value.
        timeout: Subprocess timeout in seconds.

    Returns:
        CLIResult with command output.
    """
    cmd = build_command(prompt, agent, model, budget)
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=_clean_agent_env(),
        )
    except FileNotFoundError:
        return CLIResult(
            stdout="", stderr=f"Agent binary not found: {cmd[0]}", exit_code=-1,
        )

    display_agent_boundary("agent output")
    stderr_lines: list[str] = []
    for line in proc.stderr:
        sys.stderr.write(line)
        stderr_lines.append(line)
    display_agent_boundary("end agent output")

    try:
        stdout_text, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return CLIResult(
            stdout="", stderr=f"Agent timeout after {timeout}s", exit_code=-1,
        )

    return parse_cli_output(
        stdout_text or "", "".join(stderr_lines), proc.returncode,
    )


def build_interactive_command(
    system_prompt: str,
    agent: str,
    model: str,
    allowed_tools: str = "Write,Read,Bash,Glob,Grep",
) -> list[str]:
    """Build a CLI command for an interactive agent session.

    Args:
        system_prompt: System-level instructions for the agent.
        agent: Agent name (claude or codex).
        model: Model name to use.
        allowed_tools: Comma-separated tool names the agent may use.

    Returns:
        List of command arguments.
    """
    if agent == _AGENT_CLAUDE:
        return [
            _AGENT_CLAUDE,
            "--system-prompt",
            system_prompt,
            _MODEL_FLAG,
            model,
            _ALLOWED_TOOLS_FLAG,
            allowed_tools,
        ]
    if agent == _AGENT_CODEX:
        cmd = [_AGENT_CODEX, _SKIP_GIT_REPO_CHECK_FLAG]
        if model:
            cmd.extend([_MODEL_FLAG, model])
        return cmd
    raise ValueError(f"Unknown agent: {agent}")


def run_interactive_agent(
    system_prompt: str,
    agent: str,
    model: str,
    cwd: Path,
    allowed_tools: str = "Write,Read,Bash,Glob,Grep",
    timeout: int = INTERACTIVE_AGENT_TIMEOUT_SEC,
) -> tuple[int, str]:
    """Run an agent interactively with terminal passthrough.

    Args:
        system_prompt: System-level instructions for the agent.
        agent: Agent name (claude or codex).
        model: Model name to use.
        cwd: Working directory for the agent subprocess.
        allowed_tools: Comma-separated tool names the agent may use.
        timeout: Subprocess timeout in seconds.

    Returns:
        Tuple of (exit_code, error_message). Error message is empty on success.
    """
    cmd = build_interactive_command(system_prompt, agent, model, allowed_tools)
    try:
        result = subprocess.run(cmd, cwd=str(cwd), timeout=timeout, env=_clean_agent_env())
    except subprocess.TimeoutExpired:
        return (-1, f"Agent timed out after {timeout}s")
    except FileNotFoundError:
        return (-1, f"Agent binary '{cmd[0]}' not found on PATH")
    return (result.returncode, "")
