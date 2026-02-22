"""Subprocess wrapper for running Claude Code and Codex CLIs."""

import contextlib
import json
import re
import subprocess

from pathlib import Path

from crucis.cli.constants import CLI_AGENT_TIMEOUT_SEC, INTERACTIVE_AGENT_TIMEOUT_SEC
from crucis.models import CLIResult

_AGENT_CLAUDE = "claude"
_AGENT_CODEX = "codex"
_MODEL_FLAG = "--model"
_ALLOWED_TOOLS_FLAG = "--allowedTools"
_RATE_LIMIT_RE = re.compile(
    r"usage limit|rate.?limit|Too Many Requests|error code:\s*429",
    re.IGNORECASE,
)
_NON_TRANSIENT_RE = re.compile(
    r"not inside a trusted directory|cannot be launched inside another|CLAUDECODE",
    re.IGNORECASE,
)


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
        cmd = [_AGENT_CODEX, "exec"]
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
        cmd = [_AGENT_CODEX, "exec", "--full-auto"]
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


def is_non_transient_error(stderr: str) -> bool:
    """Check whether stderr contains an error that will never self-resolve.

    Args:
        stderr: Standard error output from the agent subprocess.

    Returns:
        True when the output indicates a non-transient failure.
    """
    return bool(_NON_TRANSIENT_RE.search(stderr))


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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return CLIResult(
            stdout="",
            stderr=f"Agent timeout after {timeout}s",
            exit_code=-1,
        )
    except FileNotFoundError:
        return CLIResult(
            stdout="",
            stderr=f"Agent binary not found: {cmd[0]}",
            exit_code=-1,
        )
    return parse_cli_output(result.stdout, result.stderr, result.returncode)


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
        cmd = [_AGENT_CODEX]
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
) -> int:
    """Run an agent interactively with terminal passthrough.

    Args:
        system_prompt: System-level instructions for the agent.
        agent: Agent name (claude or codex).
        model: Model name to use.
        cwd: Working directory for the agent subprocess.
        allowed_tools: Comma-separated tool names the agent may use.
        timeout: Subprocess timeout in seconds.

    Returns:
        Process exit code (0 for success).
    """
    cmd = build_interactive_command(system_prompt, agent, model, allowed_tools)
    try:
        result = subprocess.run(cmd, cwd=str(cwd), timeout=timeout)
    except subprocess.TimeoutExpired:
        return -1
    except FileNotFoundError:
        return -1
    return result.returncode
