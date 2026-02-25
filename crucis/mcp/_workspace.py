"""Workspace resolution, path safety, and authorization for the Crucis MCP server."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from crucis.config import Config
from crucis.defaults import DEFAULT_CHECKPOINT_PATH, DEFAULT_PROFILES_PATH

_OBJECTIVE_FILENAME = "objective.yaml"
_MCP_ENABLED_FILENAME = ".crucis/mcp_enabled"
_MAX_SOURCE_INPUT_BYTES = 1_048_576  # 1 MB
_MAX_PATH_LENGTH = 4096

logger = logging.getLogger("crucis.mcp")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PathTraversalError(ValueError):
    """Raised when a resolved path escapes the workspace boundary."""


class WorkspaceNotAuthorizedError(PermissionError):
    """Raised when the workspace has not opted into MCP access."""


class InputTooLargeError(ValueError):
    """Raised when an input exceeds size limits."""


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

def check_workspace_authorized(workspace: Path) -> None:
    """Verify the workspace has opted into MCP server access.

    Authorization requires one of:
    - ``CRUCIS_MCP_AUTHORIZED=1`` environment variable, OR
    - A ``.crucis/mcp_enabled`` marker file in the workspace

    Args:
        workspace: Workspace root to check.

    Raises:
        WorkspaceNotAuthorizedError: If neither authorization method is present.
    """
    if os.environ.get("CRUCIS_MCP_AUTHORIZED") == "1":
        return
    marker = workspace / _MCP_ENABLED_FILENAME
    if marker.exists():
        return
    raise WorkspaceNotAuthorizedError(
        f"Workspace '{workspace}' has not authorized MCP access. "
        f"Create '{_MCP_ENABLED_FILENAME}' in the workspace or set "
        "CRUCIS_MCP_AUTHORIZED=1 in the server environment."
    )


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

def validate_path_within_workspace(path: Path, workspace: Path) -> Path:
    """Ensure a resolved path stays within the workspace boundary.

    Resolves symlinks before checking containment to prevent symlink-based
    traversal attacks.

    Args:
        path: Path to validate (must already be resolved).
        workspace: Workspace root boundary.

    Returns:
        The validated resolved path.

    Raises:
        PathTraversalError: If the path escapes the workspace.
    """
    resolved = path.resolve()
    ws_resolved = workspace.resolve()
    try:
        resolved.relative_to(ws_resolved)
    except ValueError:
        logger.warning("Path traversal blocked: %s (workspace: %s)", resolved, ws_resolved)
        raise PathTraversalError(
            f"Path '{resolved}' is outside workspace '{ws_resolved}'. "
            "All file operations must stay within the workspace boundary."
        )
    return resolved


def safe_resolve_path(
    override: str | None,
    default: Path,
    workspace: Path,
) -> Path:
    """Resolve a file path and validate it stays within the workspace.

    Args:
        override: Optional override path string from tool input.
        default: Default path if override is None.
        workspace: Workspace boundary for traversal checks.

    Returns:
        Resolved, validated absolute path.
    """
    if override:
        raw = override
        if "\x00" in raw:
            raise PathTraversalError("Null bytes are not allowed in file paths.")
        if len(raw) > _MAX_PATH_LENGTH:
            raise PathTraversalError(f"Path exceeds maximum length of {_MAX_PATH_LENGTH}.")
        p = Path(raw)
        resolved = p.resolve() if p.is_absolute() else (workspace / p).resolve()
    else:
        resolved = default if default.is_absolute() else default.resolve()
    return validate_path_within_workspace(resolved, workspace)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def validate_source_input(source_code: str) -> None:
    """Validate source code input size.

    Args:
        source_code: Python source code string.

    Raises:
        InputTooLargeError: If the source exceeds the size limit.
    """
    size = len(source_code.encode("utf-8", errors="replace"))
    if size > _MAX_SOURCE_INPUT_BYTES:
        raise InputTooLargeError(
            f"Source code input is {size:,} bytes, exceeding the "
            f"{_MAX_SOURCE_INPUT_BYTES:,} byte limit."
        )


# ---------------------------------------------------------------------------
# Workspace context
# ---------------------------------------------------------------------------

@dataclass
class WorkspaceContext:
    """Resolved workspace state shared across MCP tool invocations."""

    workspace: Path
    config: Config = field(default_factory=Config)

    @property
    def objective_path(self) -> Path:
        """Default objective file path.

        Returns:
            Resolved objective path within the workspace.
        """
        return self.workspace / _OBJECTIVE_FILENAME

    @property
    def profiles_path(self) -> Path:
        """Default constraint profiles file path.

        Returns:
            Resolved profiles path within the workspace.
        """
        return self.workspace / DEFAULT_PROFILES_PATH

    @property
    def checkpoint_path(self) -> Path:
        """Default checkpoint file path.

        Returns:
            Resolved checkpoint path within the workspace.
        """
        return self.workspace / DEFAULT_CHECKPOINT_PATH

    @property
    def has_objective(self) -> bool:
        """Whether objective.yaml exists in the workspace.

        Returns:
            True when the objective file is present.
        """
        return self.objective_path.exists()


def resolve_workspace(override: str | None = None) -> Path:
    """Resolve workspace from explicit override, env var, or cwd.

    Args:
        override: Explicit workspace path override.

    Returns:
        Resolved workspace root path.
    """
    if override:
        return Path(override).resolve()
    env_ws = os.environ.get("CRUCIS_WORKSPACE")
    if env_ws:
        return Path(env_ws).resolve()
    return Path.cwd().resolve()


# Keep backward compat — old resolve_path without workspace validation.
def resolve_path(override: str | None, default: Path) -> Path:
    """Resolve a file path from an override string or a default.

    Args:
        override: Optional override path string.
        default: Default path if override is None.

    Returns:
        Resolved absolute path.
    """
    if override:
        p = Path(override)
        return p.resolve() if p.is_absolute() else (resolve_workspace() / p).resolve()
    return default if default.is_absolute() else default.resolve()
