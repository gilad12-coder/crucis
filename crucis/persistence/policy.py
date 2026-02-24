"""Persistence helpers for optimizer policy artifacts."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        """Backport of StrEnum for Python 3.10."""

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from crucis.defaults import TEXT_ENCODING
from crucis.persistence.constants import MAX_POLICY_FIELD_CHARS, POLICY_OVERRIDE_ENV
from crucis.persistence.settings import crucis_dir


class OptimizerState(StrEnum):
    """Lifecycle states for the background optimizer."""

    idle = "idle"
    running = "running"
    completed = "completed"
    failed = "failed"


class OptimizerPolicy(BaseModel):
    """Optimized policy artifact used to steer Crucis prompts."""

    model_config = ConfigDict(extra="forbid")

    repository_skill: str = ""
    generation_directives: str = ""
    adversary_directives: str = ""
    evaluation_directives: str = ""

    @field_validator(
        "repository_skill",
        "generation_directives",
        "adversary_directives",
        "evaluation_directives",
    )
    @classmethod
    def _bounded_fields(cls, value: str) -> str:
        """bounded fields.

        Args:
            value: Candidate field value being validated.

        Returns:
            Computed text result for this operation.
        """
        if len(value) > MAX_POLICY_FIELD_CHARS:
            raise ValueError(f"Policy field exceeds {MAX_POLICY_FIELD_CHARS} characters")
        return value

    def to_candidate(self) -> dict[str, str]:
        """Return the GEPA candidate dictionary representation.

        Returns:
            Computed text result for this operation.
        """
        return {
            "repository_skill": self.repository_skill,
            "generation_directives": self.generation_directives,
            "adversary_directives": self.adversary_directives,
            "evaluation_directives": self.evaluation_directives,
        }

    @classmethod
    def from_candidate(cls, candidate: dict[str, str]) -> OptimizerPolicy:
        """Validate a GEPA candidate dictionary and build a policy.

        Args:
            candidate: Candidate policy dictionary under evaluation.

        Returns:
            Result of `from_candidate`.
        """
        expected = {
            "repository_skill",
            "generation_directives",
            "adversary_directives",
            "evaluation_directives",
        }
        keys = set(candidate.keys())
        if keys != expected:
            raise ValueError(
                "Policy candidate must contain exactly keys: "
                "repository_skill, generation_directives, "
                "adversary_directives, evaluation_directives"
            )
        return cls.model_validate(candidate)


class OptimizerStatus(BaseModel):
    """Minimal status view for displaying optimizer state."""

    state: str = OptimizerState.idle
    last_run_id: str | None = None
    last_trigger: str | None = None
    promoted: bool | None = None
    message: str | None = None
    updated_at: str | None = None
    active_policy_version: str | None = None
    last_candidate_score: float | None = Field(default=None)
    last_baseline_score: float | None = Field(default=None)
    candidate_ready: bool = False
    candidate_run_id: str | None = None


def optimizer_root(workspace: Path) -> Path:
    """Return root optimizer directory path.

    Args:
        workspace: Workspace root directory.

    Returns:
        Resolved filesystem path for this operation.
    """
    return crucis_dir(workspace) / "optimizer"


def active_policy_path(workspace: Path) -> Path:
    """Return active policy file path.

    Args:
        workspace: Workspace root directory.

    Returns:
        Resolved filesystem path for this operation.
    """
    return optimizer_root(workspace) / "active_policy.yaml"


def status_path(workspace: Path) -> Path:
    """Return optimizer status path.

    Args:
        workspace: Workspace root directory.

    Returns:
        Resolved filesystem path for this operation.
    """
    return optimizer_root(workspace) / "status.json"


def queue_dir(workspace: Path) -> Path:
    """Return queued jobs directory path.

    Args:
        workspace: Workspace root directory.

    Returns:
        Resolved filesystem path for this operation.
    """
    return optimizer_root(workspace) / "queue"


def runs_dir(workspace: Path) -> Path:
    """Return optimizer runs directory path.

    Args:
        workspace: Workspace root directory.

    Returns:
        Resolved filesystem path for this operation.
    """
    return optimizer_root(workspace) / "runs"


def run_dir(workspace: Path, run_id: str) -> Path:
    """Return one optimizer run directory path.

    Args:
        workspace: Workspace root directory.
        run_id: Optimizer run identifier.

    Returns:
        Resolved filesystem path for this operation.
    """
    return runs_dir(workspace) / run_id


def candidate_policy_path(workspace: Path, run_id: str) -> Path:
    """Return candidate policy artifact path for one run.

    Args:
        workspace: Workspace root directory.
        run_id: Optimizer run identifier.

    Returns:
        Resolved filesystem path for this operation.
    """
    return run_dir(workspace, run_id) / "candidate_policy.yaml"


def lock_path(workspace: Path) -> Path:
    """Return worker lock file path.

    Args:
        workspace: Workspace root directory.

    Returns:
        Resolved filesystem path for this operation.
    """
    return optimizer_root(workspace) / "worker.lock"


def load_active_policy(
    workspace: Path,
    *,
    allow_env_override: bool = True,
) -> OptimizerPolicy:
    """Load active policy from env override or persisted file.

    Args:
        workspace: Workspace root directory.
        allow_env_override: Value for `allow_env_override` used by `load_active_policy`.

    Returns:
        Loaded value for the requested resource.
    """
    if allow_env_override:
        raw_override = os.environ.get(POLICY_OVERRIDE_ENV)
        if raw_override:
            data = json.loads(raw_override)
            if not isinstance(data, dict):
                raise ValueError("CRUCIS_POLICY_OVERRIDE_JSON must encode an object")
            return OptimizerPolicy.from_candidate(data)

    path = active_policy_path(workspace)
    if not path.exists():
        return OptimizerPolicy()

    data = yaml.safe_load(path.read_text(encoding=TEXT_ENCODING)) or {}
    if not isinstance(data, dict):
        raise ValueError("Active policy file must contain a mapping")
    return OptimizerPolicy.model_validate(data)


def save_active_policy(policy: OptimizerPolicy, workspace: Path) -> Path:
    """Persist active policy to disk.

    Args:
        policy: Active optimizer policy used for prompt steering.
        workspace: Workspace root directory.

    Returns:
        Resolved filesystem path for this operation.
    """
    path = active_policy_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(policy.model_dump(mode="json"), sort_keys=False),
        encoding=TEXT_ENCODING,
    )
    return path


def load_candidate_policy(workspace: Path, run_id: str) -> OptimizerPolicy:
    """Load candidate policy from one optimizer run artifact.

    Args:
        workspace: Workspace root directory.
        run_id: Optimizer run identifier.

    Returns:
        Loaded value for the requested resource.
    """
    path = candidate_policy_path(workspace, run_id)
    if not path.exists():
        raise FileNotFoundError(f"No candidate policy found for run `{run_id}` at {path}")
    data = yaml.safe_load(path.read_text(encoding=TEXT_ENCODING)) or {}
    if not isinstance(data, dict):
        raise ValueError("Candidate policy file must contain a mapping")
    return OptimizerPolicy.model_validate(data)


def save_candidate_policy(
    policy: OptimizerPolicy,
    workspace: Path,
    run_id: str,
) -> Path:
    """Persist candidate policy for one optimizer run.

    Args:
        policy: Active optimizer policy used for prompt steering.
        workspace: Workspace root directory.
        run_id: Optimizer run identifier.

    Returns:
        Resolved filesystem path for this operation.
    """
    path = candidate_policy_path(workspace, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(policy.model_dump(mode="json"), sort_keys=False),
        encoding=TEXT_ENCODING,
    )
    return path


def load_optimizer_status(workspace: Path) -> OptimizerStatus | None:
    """Load optimizer status from JSON if present.

    Args:
        workspace: Workspace root directory.

    Returns:
        None.
    """
    path = status_path(workspace)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding=TEXT_ENCODING))
    if not isinstance(data, dict):
        return None
    return OptimizerStatus.model_validate(data)


def save_optimizer_status(workspace: Path, status: OptimizerStatus) -> Path:
    """Persist optimizer status to disk.

    Args:
        workspace: Workspace root directory.
        status: Value for `status` used by `save_optimizer_status`.

    Returns:
        Resolved filesystem path for this operation.
    """
    path = status_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        status.model_dump_json(indent=2),
        encoding=TEXT_ENCODING,
    )
    return path
