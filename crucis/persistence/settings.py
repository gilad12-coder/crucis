"""Runtime settings for Crucis background optimization."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from crucis.defaults import TEXT_ENCODING
from crucis.persistence.constants import CRUCIS_DIR_NAME


class OptimizerRuntimeSettings(BaseModel):
    """Settings that control GEPA background optimization behavior."""

    enabled: bool = True
    max_metric_calls: int = Field(default=24, ge=1)
    reflection_lm: str = "openai/gpt-5.1"
    train_split_ratio: float = Field(default=0.7, gt=0.0, lt=1.0)
    max_examples_per_run: int = Field(default=24, ge=1)
    evaluator_timeout_sec: int = Field(default=180, ge=10)
    pass_weight: float = Field(default=0.9, ge=0.0, le=1.0)
    speed_weight: float = Field(default=0.1, ge=0.0, le=1.0)
    min_score_delta: float = Field(default=0.01, ge=0.0)
    promotion_mode: Literal["manual", "auto"] = "manual"
    queue_max_jobs: int = Field(default=64, ge=1)
    capture_stdio: bool = True

    @model_validator(mode="before")
    @classmethod
    def _map_legacy_auto_on_val_win(cls, value):
        """map legacy auto on val win.

        Args:
            value: Candidate field value being validated.

        Returns:
            Result of `_map_legacy_auto_on_val_win`.
        """
        if not isinstance(value, dict):
            return value

        if "promotion_mode" not in value and "auto_on_val_win" in value:
            value = dict(value)
            value["promotion_mode"] = "auto" if bool(value.get("auto_on_val_win")) else "manual"
        return value

    @model_validator(mode="after")
    def _validate_weights(self) -> OptimizerRuntimeSettings:
        """validate weights.

        Returns:
            Result of `_validate_weights`.
        """
        if self.pass_weight + self.speed_weight <= 0:
            raise ValueError("pass_weight + speed_weight must be > 0")
        return self


class AgentSettings(BaseModel):
    """Optional agent configuration surfaced in settings YAML.

    Fields default to None, meaning "use Config/env default".
    """

    generation_agent: str | None = None
    generation_model: str | None = None
    critic_agent: str | None = None
    critic_model: str | None = None
    implementation_agent: str | None = None
    implementation_model: str | None = None
    max_iterations: int | None = None
    max_budget_usd: float | None = None


class RuntimeSettings(BaseModel):
    """Top-level runtime settings container."""

    schema_version: int = 1
    optimizer: OptimizerRuntimeSettings = Field(default_factory=OptimizerRuntimeSettings)
    agents: AgentSettings = Field(default_factory=AgentSettings)


def crucis_dir(workspace: Path) -> Path:
    """Return the workspace-local Crucis settings directory.

    Args:
        workspace: Workspace root directory.

    Returns:
        Resolved filesystem path for this operation.
    """
    return workspace / CRUCIS_DIR_NAME


def settings_path(workspace: Path) -> Path:
    """Return the settings file path for a workspace.

    Args:
        workspace: Workspace root directory.

    Returns:
        Resolved filesystem path for this operation.
    """
    return crucis_dir(workspace) / "settings.yaml"


def default_runtime_settings() -> RuntimeSettings:
    """Build default runtime settings.

    Returns:
        Result of `default_runtime_settings`.
    """
    return RuntimeSettings()


def save_runtime_settings(settings: RuntimeSettings, workspace: Path) -> Path:
    """Persist runtime settings to ``.crucis/settings.yaml``.

    Args:
        settings: Loaded runtime optimizer settings.
        workspace: Workspace root directory.

    Returns:
        Resolved filesystem path for this operation.
    """
    path = settings_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.safe_dump(
        settings.model_dump(mode="json"),
        sort_keys=False,
    )
    path.write_text(content, encoding=TEXT_ENCODING)
    return path


def load_runtime_settings(workspace: Path) -> RuntimeSettings:
    """Load runtime settings, writing defaults when no file exists.

    Args:
        workspace: Workspace root directory.

    Returns:
        Loaded value for the requested resource.
    """
    path = settings_path(workspace)
    if not path.exists():
        settings = default_runtime_settings()
        save_runtime_settings(settings, workspace)
        return settings

    raw = yaml.safe_load(path.read_text(encoding=TEXT_ENCODING))
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("Runtime settings file must contain a mapping")

    return RuntimeSettings.model_validate(raw)


_AGENT_MODEL_PAIRS: tuple[tuple[str, str], ...] = (
    ("generation_agent", "generation_model"),
    ("critic_agent", "critic_model"),
    ("implementation_agent", "implementation_model"),
)
"""Paired agent/model field names for coherent default resolution."""

_AGENT_DEFAULT_MODELS: dict[str, str] = {
    "claude": "claude-opus-4-6",
    "codex": "",
}
"""Default model for each known agent. Empty string means use agent built-in default."""


def apply_agent_settings_to_env(settings: RuntimeSettings) -> None:
    """Set environment variables from YAML agent settings when not already set.

    Only non-None fields are exported. Explicit env vars always take priority.
    When an agent is set but its corresponding model is not, the model env var
    is filled with the agent's known default to prevent cross-agent mismatches.

    Args:
        settings: Loaded runtime settings containing agent overrides.
    """
    dumped = settings.agents.model_dump()
    for field_name, value in dumped.items():
        if value is None:
            continue
        env_key = field_name.upper()
        if env_key not in os.environ:
            os.environ[env_key] = str(value)
    _fill_missing_model_defaults(dumped)


def _fill_missing_model_defaults(agent_fields: dict) -> None:
    """Fill model env vars when an agent is set but its model is not.

    For each agent/model pair, if the agent env var is present but the model
    env var is absent and the user did not provide a model in YAML, the model
    is set to the agent's known default.

    Args:
        agent_fields: Dumped AgentSettings field values (may contain None).
    """
    for agent_key, model_key in _AGENT_MODEL_PAIRS:
        agent_env = agent_key.upper()
        model_env = model_key.upper()
        agent_value = os.environ.get(agent_env)
        if not agent_value:
            continue
        if model_env in os.environ:
            continue
        if agent_fields.get(model_key) is not None:
            continue
        default_model = _AGENT_DEFAULT_MODELS.get(agent_value)
        if default_model is not None:
            os.environ[model_env] = default_model
