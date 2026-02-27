"""Runtime diagnostics and preflight checks for Crucis."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

from crucis.config import Config
from crucis.constraints.loader import load_profiles
from crucis.defaults import TEXT_ENCODING
from crucis.execution.sandbox import check_docker_available
from crucis.intake.objective import parse_objective
from crucis.persistence.checkpoint import load_checkpoint
from crucis.persistence.settings import (
    REFLECTION_LM_PREFIX_TO_ENV,
    RuntimeSettings,
    settings_path,
    try_load_runtime_settings,
)


_MASK_THRESHOLD = 8
_MASK_VISIBLE = 4
_STATUS_OK = "ok"
_STATUS_FAIL = "fail"
_STATUS_WARN = "warn"
_SUBPROCESS_TIMEOUT_SEC = 5

_CHECK_PYTHON_VERSION = "python_version"
_CHECK_PYTEST = "pytest"
_CHECK_RUNTIME_SETTINGS = "runtime_settings"
_CHECK_DOCKER = "docker"
_CHECK_OBJECTIVE = "objective"
_CHECK_PROFILES = "profiles"
_CHECK_CHECKPOINT = "checkpoint"
_AGENT_CLAUDE = "claude"
_AGENT_CODEX = "codex"


def mask_api_key(key: str) -> str:
    """Mask an API key for safe display in logs and diagnostics.

    Args:
        key: Raw API key string.

    Returns:
        Masked key showing first 4 and last 4 chars for long keys,
        or all asterisks for short keys.
    """
    if not key:
        return ""
    if len(key) < _MASK_THRESHOLD:
        return "*" * len(key)
    return key[:_MASK_VISIBLE] + "..." + key[-_MASK_VISIBLE:]


@dataclass(slots=True)
class DiagnosticCheck:
    """One diagnostics check outcome."""

    id: str
    status: str
    message: str
    hint: str | None = None

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible mapping.

        Returns:
            Dictionary representation of one diagnostics check.
        """
        return {
            "id": self.id,
            "status": self.status,
            "message": self.message,
            "hint": self.hint,
        }


@dataclass(slots=True)
class DoctorReport:
    """Aggregate doctor report."""

    ok: bool
    workspace: Path
    checks: list[DiagnosticCheck]


def doctor_report_payload(report: DoctorReport) -> dict:
    """Build stable JSON payload for doctor output.

    Args:
        report: Aggregated diagnostics report.

    Returns:
        JSON-compatible diagnostics payload.
    """
    return {
        "ok": report.ok,
        "workspace": str(report.workspace),
        "checks": [check.to_dict() for check in report.checks],
    }


def collect_preflight_checks(
    workspace: Path,
    config: Config,
    required_agents: Iterable[str],
    require_pytest: bool,
    require_docker: bool = False,
) -> list[DiagnosticCheck]:
    """Collect fail-fast checks used before running long workflows.

    Args:
        workspace: Workspace root directory.
        config: Runtime configuration values.
        required_agents: Agent binaries required for this flow.
        require_pytest: Whether host pytest availability is required.
        require_docker: Whether Docker availability is required.

    Returns:
        Ordered list of preflight checks.
    """
    checks: list[DiagnosticCheck] = [
        _check_python_version(),
        _check_git_repository(workspace),
    ]
    if require_pytest:
        checks.append(_check_pytest_available())

    for agent in sorted({agent for agent in required_agents if agent}):
        checks.append(_check_agent_binary(agent))

    checks.extend(_check_required_api_keys(required_agents, workspace))

    nesting_check = _check_claudecode_nesting(required_agents)
    if nesting_check is not None:
        checks.append(nesting_check)

    checks.extend(_check_agent_model_coherence(config))
    checks.append(_check_runtime_settings(workspace))

    optimizer_check = _check_optimizer_api_key(workspace)
    if optimizer_check is not None:
        checks.append(optimizer_check)

    checks.append(_check_docker(require_docker=require_docker))
    return checks


def run_doctor(
    workspace: Path,
    objective_path: Path | None = None,
    profiles_path: Path | None = None,
    checkpoint_path: Path | None = None,
    require_docker: bool = False,
    config: Config | None = None,
) -> DoctorReport:
    """Run full environment + workspace diagnostics.

    Args:
        workspace: Workspace root directory.
        objective_path: Optional objective file to validate.
        profiles_path: Optional profiles file to validate.
        checkpoint_path: Optional checkpoint file to validate.
        require_docker: Whether Docker should be treated as required.
        config: Optional runtime config override.

    Returns:
        Aggregated doctor report.
    """
    resolved_workspace = workspace.resolve()
    config = config or Config()
    checks = collect_preflight_checks(
        workspace=resolved_workspace,
        config=config,
        required_agents=[
            config.generation_agent,
            config.critic_agent,
            config.implementation_agent,
        ],
        require_pytest=True,
        require_docker=require_docker,
    )

    if objective_path is not None:
        checks.append(_check_objective(resolved_workspace, objective_path))
    if profiles_path is not None:
        checks.append(_check_profiles(resolved_workspace, profiles_path))
    if checkpoint_path is not None:
        checks.append(_check_checkpoint(resolved_workspace, checkpoint_path))

    return DoctorReport(
        ok=not any(check.status == _STATUS_FAIL for check in checks),
        workspace=resolved_workspace,
        checks=checks,
    )


def _resolve_input_path(workspace: Path, path: Path) -> Path:
    """Resolve absolute/relative CLI path against workspace.

    Args:
        workspace: Workspace root directory.
        path: Path argument from CLI.

    Returns:
        Resolved path anchored to workspace when relative.
    """
    if path.is_absolute():
        return path
    return workspace / path


def _check_git_repository(workspace: Path) -> DiagnosticCheck:
    """Check that the workspace is inside a git repository.

    Args:
        workspace: Workspace root directory.

    Returns:
        Result of git repository detection check.
    """
    path = workspace.resolve()
    while path != path.parent:
        if (path / ".git").exists():
            return DiagnosticCheck(
                id="git_repository",
                status=_STATUS_OK,
                message=f"Git repository found at {path}",
            )
        path = path.parent
    return DiagnosticCheck(
        id="git_repository",
        status=_STATUS_WARN,
        message="Workspace is not inside a git repository",
        hint=(
            "Run `git init` or clone a repository. "
            "Some agents (e.g. codex) require a trusted git directory."
        ),
    )


_RECOMMENDED_PYTHON = (3, 12)
_MINIMUM_PYTHON = (3, 10)


def _check_python_version() -> DiagnosticCheck:
    """Validate interpreter version.

    Returns:
        Result of Python version diagnostics check.
    """
    version = sys.version_info
    current = (version.major, version.minor)
    label = f"Python {version.major}.{version.minor}.{version.micro}"
    if current >= _RECOMMENDED_PYTHON:
        return DiagnosticCheck(
            id=_CHECK_PYTHON_VERSION,
            status=_STATUS_OK,
            message=label,
        )
    if current >= _MINIMUM_PYTHON:
        return DiagnosticCheck(
            id=_CHECK_PYTHON_VERSION,
            status=_STATUS_OK,
            message=f"{label} (3.12+ recommended)",
        )
    return DiagnosticCheck(
        id=_CHECK_PYTHON_VERSION,
        status=_STATUS_FAIL,
        message=f"{label} is unsupported (requires >=3.10)",
        hint="Use Python 3.10+ and recreate the environment.",
    )


def _check_pytest_available() -> DiagnosticCheck:
    """Validate pytest importability for host verification paths.

    Returns:
        Result of pytest module availability check.
    """
    if importlib.util.find_spec("pytest") is not None:
        return DiagnosticCheck(
            id=_CHECK_PYTEST,
            status=_STATUS_OK,
            message="pytest module is importable",
        )
    return DiagnosticCheck(
        id=_CHECK_PYTEST,
        status=_STATUS_FAIL,
        message="pytest module is not installed in this environment",
        hint="Install pytest in the active environment (for example: `pip install pytest`).",
    )


def _check_agent_binary(agent_binary: str) -> DiagnosticCheck:
    """Validate agent binary is discoverable on PATH.

    Args:
        agent_binary: Agent executable name.

    Returns:
        Result of binary discovery check.
    """
    resolved = shutil.which(agent_binary)
    if resolved:
        return DiagnosticCheck(
            id=f"agent_{agent_binary}",
            status=_STATUS_OK,
            message=f"Agent binary `{agent_binary}` found at {resolved}",
        )
    return DiagnosticCheck(
        id=f"agent_{agent_binary}",
        status=_STATUS_FAIL,
        message=f"Agent binary `{agent_binary}` not found on PATH",
        hint=f"Install `{agent_binary}` and ensure it is available on PATH.",
    )


_AGENT_API_KEYS: dict[str, str] = {
    _AGENT_CLAUDE: "ANTHROPIC_API_KEY",
    _AGENT_CODEX: "OPENAI_API_KEY",
}
"""Environment variable required by each known agent."""


def _has_claude_login_session() -> bool:
    """Check whether Claude CLI has an active authenticated session.

    Returns:
        True if Claude CLI reports loggedIn status.
    """
    claude_binary = shutil.which(_AGENT_CLAUDE)
    if claude_binary is None:
        return False
    try:
        result = subprocess.run(
            [claude_binary, "auth", "status"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_SUBPROCESS_TIMEOUT_SEC,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    output = result.stdout.strip()
    return '"loggedIn": true' in output or '"loggedIn":true' in output


def _has_codex_login_session() -> bool:
    """Check whether Codex CLI has an active authenticated session.

    Returns:
        True if Codex CLI reports an active login.
    """
    codex_binary = shutil.which(_AGENT_CODEX)
    if codex_binary is None:
        return False
    try:
        result = subprocess.run(
            [codex_binary, "login", "status"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_SUBPROCESS_TIMEOUT_SEC,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip().lower()
    return "logged in" in output


def _check_required_api_keys(
    required_agents: Iterable[str],
    workspace: Path | None = None,
) -> list[DiagnosticCheck]:
    """Check that API keys are set for the configured agents.

    Args:
        required_agents: Agent binaries required for this flow.
        workspace: Workspace root directory (used to check YAML api_key).

    Returns:
        List of API key availability checks.
    """
    yaml_key: str | None = None
    if workspace is not None:
        settings = try_load_runtime_settings(workspace)
        if settings is not None:
            yaml_key = settings.agents.api_key or None
    checks: list[DiagnosticCheck] = []
    seen: set[str] = set()
    for agent in sorted({a for a in required_agents if a}):
        env_key = _AGENT_API_KEYS.get(agent)
        if env_key is None or env_key in seen:
            continue
        seen.add(env_key)
        if os.environ.get(env_key) or yaml_key:
            checks.append(
                DiagnosticCheck(
                    id=f"api_key_{agent}",
                    status=_STATUS_OK,
                    message=f"{env_key} is set",
                )
            )
            continue
        if agent == _AGENT_CLAUDE and _has_claude_login_session():
            checks.append(
                DiagnosticCheck(
                    id="api_key_claude",
                    status=_STATUS_OK,
                    message="Claude CLI login session is active (ANTHROPIC_API_KEY not required)",
                )
            )
            continue
        if agent == _AGENT_CODEX and _has_codex_login_session():
            checks.append(
                DiagnosticCheck(
                    id="api_key_codex",
                    status=_STATUS_OK,
                    message="Codex CLI login session is active (OPENAI_API_KEY not required)",
                )
            )
            continue

        hint = (
            f"Set api_key in .crucis/settings.yaml, run `{agent} login`, "
            f"or export {env_key}."
        )
        checks.append(
            DiagnosticCheck(
                id=f"api_key_{agent}",
                status=_STATUS_WARN,
                message=f"{env_key} is not set (required by {agent} agent)",
                hint=hint,
            )
        )
    return checks


_AGENT_MODEL_PREFIXES: dict[str, tuple[str, ...]] = {
    _AGENT_CLAUDE: ("claude-", "sonnet", "haiku", "opus"),
    _AGENT_CODEX: ("gpt-", "o1", "o3", "o4", _AGENT_CODEX),
}
"""Known model-name prefixes associated with each agent."""


def _check_agent_model_coherence(config: Config) -> list[DiagnosticCheck]:
    """Warn when agent/model pairs appear mismatched.

    Args:
        config: Runtime configuration values.

    Returns:
        List of warning checks for mismatched agent/model pairs.
    """
    checks: list[DiagnosticCheck] = []
    pairs = (
        ("generation", config.generation_agent, config.generation_model),
        ("critic", config.critic_agent, config.critic_model),
        ("implementation", config.implementation_agent, config.implementation_model),
    )
    for role, agent, model in pairs:
        if not model:
            continue
        expected = _AGENT_MODEL_PREFIXES.get(agent)
        if expected is None:
            continue
        if any(model.startswith(prefix) for prefix in expected):
            continue
        checks.append(
            DiagnosticCheck(
                id=f"agent_model_{role}",
                status=_STATUS_WARN,
                message=(
                    f"{role}_agent={agent!r} with {role}_model={model!r} "
                    "looks like a cross-agent mismatch"
                ),
                hint=(
                    f"Set {role.upper()}_MODEL in .crucis/settings.yaml to a model "
                    f"compatible with {agent}, or leave it unset for the agent default."
                ),
            )
        )
    return checks


def _check_claudecode_nesting(required_agents: Iterable[str]) -> DiagnosticCheck | None:
    """Warn when running inside Claude Code with claude as an agent.

    Args:
        required_agents: Agent binaries required for this flow.

    Returns:
        Warning check when nesting is detected, None otherwise.
    """
    if not os.environ.get("CLAUDECODE"):
        return None
    if _AGENT_CLAUDE not in set(required_agents):
        return None
    return DiagnosticCheck(
        id="claudecode_nesting",
        status=_STATUS_WARN,
        message="Running inside Claude Code with 'claude' as an agent may fail",
        hint=(
            "Set GENERATION_AGENT=codex in .crucis/settings.yaml "
            "or run crucis outside Claude Code."
        ),
    )


def _check_runtime_settings(workspace: Path) -> DiagnosticCheck:
    """Validate runtime settings file shape if it exists.

    Args:
        workspace: Workspace root directory.

    Returns:
        Result of runtime settings validation check.
    """
    path = settings_path(workspace)
    if not path.exists():
        return DiagnosticCheck(
            id=_CHECK_RUNTIME_SETTINGS,
            status=_STATUS_WARN,
            message=f"No runtime settings file at {path}",
            hint="It will be created automatically on first run.",
        )

    try:
        raw = yaml.safe_load(path.read_text(encoding=TEXT_ENCODING))
    except Exception as exc:
        return DiagnosticCheck(
            id=_CHECK_RUNTIME_SETTINGS,
            status=_STATUS_FAIL,
            message=f"Could not read runtime settings: {exc}",
            hint="Fix or remove `.crucis/settings.yaml` and retry.",
        )

    try:
        RuntimeSettings.model_validate(raw or {})
    except Exception as exc:
        return DiagnosticCheck(
            id=_CHECK_RUNTIME_SETTINGS,
            status=_STATUS_FAIL,
            message=f"Runtime settings are invalid: {exc}",
            hint="Fix `.crucis/settings.yaml` schema values.",
        )

    return DiagnosticCheck(
        id=_CHECK_RUNTIME_SETTINGS,
        status=_STATUS_OK,
        message=f"Runtime settings valid at {path}",
    )


def _check_optimizer_api_key(workspace: Path) -> DiagnosticCheck | None:
    """Warn when the optimizer's reflection_lm API key is missing.

    Args:
        workspace: Workspace root directory.

    Returns:
        Warning check when key is missing, None when ok or optimizer disabled.
    """
    settings = try_load_runtime_settings(workspace)
    if settings is None:
        return None
    if settings.optimizer.reflection_api_key:
        return None
    lm = settings.optimizer.reflection_lm
    for prefix, env_key in REFLECTION_LM_PREFIX_TO_ENV.items():
        if lm.startswith(prefix) and not os.environ.get(env_key):
            return DiagnosticCheck(
                id="optimizer_api_key",
                status=_STATUS_WARN,
                message=f"{env_key} is not set (required by optimizer reflection_lm `{lm}`)",
                hint=(
                    f"Set reflection_api_key in .crucis/settings.yaml, "
                    f"or export {env_key}."
                ),
            )
    return None


def _check_docker(require_docker: bool) -> DiagnosticCheck:
    """Check Docker availability (warn by default, fail when required).

    Args:
        require_docker: Whether missing Docker should fail diagnostics.

    Returns:
        Result of Docker availability check.
    """
    available = check_docker_available()
    if available:
        return DiagnosticCheck(
            id=_CHECK_DOCKER,
            status=_STATUS_OK,
            message="Docker sandbox is available",
        )
    if require_docker:
        return DiagnosticCheck(
            id=_CHECK_DOCKER,
            status=_STATUS_FAIL,
            message="Docker sandbox is unavailable",
            hint="Start Docker to enable isolated sandbox execution.",
        )
    return DiagnosticCheck(
        id=_CHECK_DOCKER,
        status=_STATUS_OK,
        message="Docker sandbox is unavailable (optional)",
    )


def _check_objective(workspace: Path, objective_path: Path) -> DiagnosticCheck:
    """Validate objective path existence and schema parseability.

    Args:
        workspace: Workspace root directory.
        objective_path: Objective path argument from CLI.

    Returns:
        Result of objective validation check.
    """
    resolved = _resolve_input_path(workspace, objective_path).resolve()
    if not resolved.exists():
        return DiagnosticCheck(
            id=_CHECK_OBJECTIVE,
            status=_STATUS_FAIL,
            message=f"Objective file not found at {resolved}",
            hint="Pass a valid objective path.",
        )
    try:
        parse_objective(resolved)
    except Exception as exc:
        return DiagnosticCheck(
            id=_CHECK_OBJECTIVE,
            status=_STATUS_FAIL,
            message=f"Objective parse failed: {exc}",
            hint="Fix objective schema/values.",
        )
    return DiagnosticCheck(
        id=_CHECK_OBJECTIVE,
        status=_STATUS_OK,
        message=f"Objective parsed successfully from {resolved}",
    )


def _check_profiles(workspace: Path, profiles_path: Path) -> DiagnosticCheck:
    """Validate profiles path existence and parseability.

    Args:
        workspace: Workspace root directory.
        profiles_path: Profiles path argument from CLI.

    Returns:
        Result of profiles validation check.
    """
    resolved = _resolve_input_path(workspace, profiles_path).resolve()
    if not resolved.exists():
        return DiagnosticCheck(
            id=_CHECK_PROFILES,
            status=_STATUS_FAIL,
            message=f"Profiles file not found at {resolved}",
            hint="Pass a valid profiles path.",
        )
    try:
        load_profiles(resolved)
    except Exception as exc:
        return DiagnosticCheck(
            id=_CHECK_PROFILES,
            status=_STATUS_FAIL,
            message=f"Profiles parse failed: {exc}",
            hint="Fix constraints profiles YAML schema.",
        )
    return DiagnosticCheck(
        id=_CHECK_PROFILES,
        status=_STATUS_OK,
        message=f"Profiles parsed successfully from {resolved}",
    )


def _check_checkpoint(workspace: Path, checkpoint_path: Path) -> DiagnosticCheck:
    """Validate checkpoint path existence and parseability.

    Args:
        workspace: Workspace root directory.
        checkpoint_path: Checkpoint path argument from CLI.

    Returns:
        Result of checkpoint validation check.
    """
    resolved = _resolve_input_path(workspace, checkpoint_path).resolve()
    if not resolved.exists():
        return DiagnosticCheck(
            id=_CHECK_CHECKPOINT,
            status=_STATUS_FAIL,
            message=f"Checkpoint file not found at {resolved}",
            hint="Run `crucis run` first or pass an existing checkpoint path.",
        )
    try:
        state = load_checkpoint(resolved)
    except Exception as exc:
        return DiagnosticCheck(
            id=_CHECK_CHECKPOINT,
            status=_STATUS_FAIL,
            message=f"Checkpoint parse failed: {exc}",
            hint="Fix or regenerate the checkpoint file.",
        )
    if state is None:
        return DiagnosticCheck(
            id=_CHECK_CHECKPOINT,
            status=_STATUS_FAIL,
            message=f"Checkpoint file not found at {resolved}",
            hint="Run `crucis run` first or pass an existing checkpoint path.",
        )
    return DiagnosticCheck(
        id=_CHECK_CHECKPOINT,
        status=_STATUS_OK,
        message=f"Checkpoint loaded successfully from {resolved}",
    )
