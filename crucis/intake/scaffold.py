"""Workspace scaffolding for `crucis init`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from crucis.defaults import TEXT_ENCODING

_OBJECTIVE_FILENAME = "objective.yaml"
_PROFILES_DIR = "constraints"
_PROFILES_FILENAME = "profiles.yaml"
_RECOMMENDED_PROFILE = "recommended"

_SETTINGS_TEMPLATE = """\
schema_version: 1

# Background optimizer (optional — requires an OpenAI API key).
# The optimizer refines generation prompts after each fit run.
optimizer:
  enabled: true
  reflection_lm: openai/gpt-5.1  # LiteLLM model string for optimizer reflection
  max_metric_calls: 24
  train_split_ratio: 0.7
  max_examples_per_run: 24
  evaluator_timeout_sec: 180
  pass_weight: 0.9
  speed_weight: 0.1
  min_score_delta: 0.01
  promotion_mode: manual  # "manual" or "auto"
  queue_max_jobs: 64
  capture_stdio: true

# Agent configuration. Valid agents: claude, codex
# Leave null to use defaults (claude / claude-opus-4-6).
agents:
  generation_agent: null   # "claude" or "codex"
  generation_model: null   # e.g. "claude-opus-4-6", "o4-mini" (null = agent default)
  critic_agent: null
  critic_model: null
  implementation_agent: null
  implementation_model: null
  max_iterations: null     # max generation/evaluation retries (null = 3)
  max_budget_usd: null     # per-agent call budget cap (null = 5.00)
"""

_TEMPLATES: dict[str, dict] = {
    "factorial": {
        "description": "Compute the factorial of a non-negative integer.",
        "signature": "factorial(n: int) -> int",
        "tasks": [
            {
                "name": "factorial",
                "description": "Return n! for non-negative n. "
                "Raise ValueError for negative input.",
                "signature": "factorial(n: int) -> int",
                "train_evals": [
                    {"input": "(0,)", "output": "1"},
                    {"input": "(1,)", "output": "1"},
                    {"input": "(5,)", "output": "120"},
                    {"input": "(10,)", "output": "3628800"},
                ],
            }
        ],
    },
}


def _build_objective(name: str) -> dict:
    """Build an objective dict from a built-in template or generic fallback.

    Args:
        name: Project name (may match a built-in template key).

    Returns:
        Objective data dict ready for YAML serialization.
    """
    template = _TEMPLATES.get(name)
    if template is not None:
        return {
            "name": name,
            "tests_constraint_profile": _RECOMMENDED_PROFILE,
            "implementation_constraint_profile": _RECOMMENDED_PROFILE,
            "target_files": ["src/solution.py"],
            **template,
        }
    return {
        "name": name,
        "description": f"Describe what {name} should do.",
        "signature": f"{name}(x: int) -> int",
        "tests_constraint_profile": _RECOMMENDED_PROFILE,
        "implementation_constraint_profile": _RECOMMENDED_PROFILE,
        "target_files": ["src/solution.py"],
        "tasks": [
            {
                "name": name,
                "description": f"Implement {name}.",
                "signature": f"{name}(x: int) -> int",
                "train_evals": [
                    {"input": "(1,)", "output": "1"},
                    {"input": "(2,)", "output": "4"},
                ],
            }
        ],
    }


_DEFAULT_PROFILES = {
    "profiles": {
        "recommended": {
            "primary": {
                "max_cyclomatic_complexity": 10,
                "max_lines_per_function": 50,
                "max_parameters": 5,
                "max_nested_depth": 4,
                "no_bare_except": True,
                "no_mutable_defaults": True,
                "no_eval": True,
                "no_exec": True,
                "no_magic_numbers": True,
            },
            "secondary": {
                "require_docstrings": True,
                "no_print_statements": True,
            },
        },
    },
    "functions": {},
}


def scaffold_workspace(workspace: Path, name: str = "my_project") -> list[Path]:
    """Create starter files for a new Crucis workspace.

    Skips any file that already exists.

    Args:
        workspace: Workspace root directory.
        name: Project name used in the objective template.

    Returns:
        List of file paths that were created.
    """
    created: list[Path] = []

    objective_data = _build_objective(name)
    objective_path = workspace / _OBJECTIVE_FILENAME
    if not objective_path.exists():
        objective_path.parent.mkdir(parents=True, exist_ok=True)
        objective_path.write_text(
            yaml.safe_dump(objective_data, sort_keys=False),
            encoding=TEXT_ENCODING,
        )
        created.append(objective_path)

    profiles_path = workspace / _PROFILES_DIR / _PROFILES_FILENAME
    if not profiles_path.exists():
        profiles_path.parent.mkdir(parents=True, exist_ok=True)
        profiles_path.write_text(
            yaml.safe_dump(_DEFAULT_PROFILES, sort_keys=False),
            encoding=TEXT_ENCODING,
        )
        created.append(profiles_path)

    from crucis.persistence.settings import settings_path

    settings_file = settings_path(workspace)
    if not settings_file.exists():
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text(_SETTINGS_TEMPLATE, encoding=TEXT_ENCODING)
        created.append(settings_file)

    target_dir = workspace / "src"
    target_file = target_dir / "solution.py"
    if not target_file.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file.write_text(
            "# Implementation will be generated during evaluation phase.\n",
            encoding=TEXT_ENCODING,
        )
        created.append(target_file)

    return created


# ---------------------------------------------------------------------------
# Agent-driven onboarding
# ---------------------------------------------------------------------------

_PROJECT_TYPE_PROFILES: dict[str, str] = {
    "library": "strict",
    "cli": "recommended",
    "web-service": "recommended",
    "script": "default",
    "data-pipeline": "default",
}

_BUILTIN_PROFILES = """\
profiles:
  default:
    primary:
      max_cyclomatic_complexity: 10
    secondary:
      require_docstrings: true

  strict:
    primary:
      max_cyclomatic_complexity: 5
      max_lines_per_function: 30
    secondary:
      require_docstrings: true

  recommended:
    primary:
      max_cyclomatic_complexity: 10
      max_cognitive_complexity: 15
      max_lines_per_function: 50
      max_parameters: 5
      max_nested_depth: 4
      no_bare_except: true
      no_unreachable_code: true
      no_mutable_defaults: true
      no_eval: true
      no_exec: true
      no_magic_numbers: true
    secondary:
      require_docstrings: true
      no_print_statements: true
      no_debugger_statements: true

  config_hygiene:
    primary:
      no_magic_numbers: true
      no_hardcoded_secrets: true
      max_string_literal_repeats: 3
    secondary:
      no_global_state: true

functions: {}
"""

_OBJECTIVE_SCHEMA = """\
name: <project_name>
description: <what the project does>
signature: <main_function(args) -> return_type>
tests_constraint_profile: recommended   # profile name from profiles.yaml
implementation_constraint_profile: recommended
target_files:
  - src/solution.py
tasks:
  - name: <task_name>
    description: <what this task does>
    signature: <function_name(args) -> return_type>
    train_evals:
      - input: "(arg1, arg2)"
        output: "expected_result"
"""


def _constraint_field_listing() -> str:
    """Generate a categorized listing of all ConstraintSet fields.

    Returns:
        Formatted text listing every available constraint field.
    """
    from crucis.models import ConstraintSet

    lines: list[str] = []
    for name, field_info in ConstraintSet.model_fields.items():
        raw = str(field_info.annotation)
        if "bool" in raw:
            type_label = "bool"
        elif "int" in raw:
            type_label = "int"
        elif "str" in raw:
            type_label = "str"
        elif "list" in raw:
            type_label = "list[str]"
        else:
            type_label = raw
        lines.append(f"  - {name} ({type_label})")
    return "\n".join(lines)


def build_onboarding_prompt() -> str:
    """Build the system prompt for the onboarding agent.

    Returns:
        System prompt text with full context for the onboarding interview.
    """
    from crucis.prompts import render

    profile_table = "\n".join(
        f"  {ptype:15s} -> {profile}"
        for ptype, profile in _PROJECT_TYPE_PROFILES.items()
    )

    return render(
        "onboarding.jinja2",
        profile_table=profile_table,
        objective_schema=_OBJECTIVE_SCHEMA,
        builtin_profiles=_BUILTIN_PROFILES,
        settings_template=_SETTINGS_TEMPLATE,
        constraint_fields_text=_constraint_field_listing(),
    )


def run_agent_onboarding(workspace: Path, agent: str, model: str) -> bool:
    """Launch an interactive agent to conduct the onboarding interview.

    Args:
        workspace: Target workspace directory.
        agent: Agent name (claude or codex).
        model: Model name to use.

    Returns:
        True when the agent completed successfully.
    """
    from crucis.cli.runner import run_interactive_agent

    workspace.mkdir(parents=True, exist_ok=True)
    prompt = build_onboarding_prompt()

    if agent == "codex":
        backup = _write_codex_instructions(workspace, prompt)
        try:
            exit_code = run_interactive_agent(prompt, agent, model, cwd=workspace)
        finally:
            _restore_agents_md(workspace, backup)
    else:
        exit_code = run_interactive_agent(prompt, agent, model, cwd=workspace)

    return exit_code == 0


def _write_codex_instructions(workspace: Path, prompt: str) -> Path | None:
    """Write onboarding instructions to AGENTS.md for Codex to read.

    Backs up any existing AGENTS.md before overwriting.

    Args:
        workspace: Target workspace directory.
        prompt: Full onboarding instructions text.

    Returns:
        Path to the backup file, or None if no backup was needed.
    """
    agents_md = workspace / "AGENTS.md"
    backup = None
    if agents_md.exists():
        backup = workspace / "AGENTS.md.crucis-backup"
        agents_md.rename(backup)
    agents_md.write_text(prompt, encoding=TEXT_ENCODING)
    return backup


def _restore_agents_md(workspace: Path, backup: Path | None) -> None:
    """Remove onboarding AGENTS.md and restore any backup.

    Args:
        workspace: Target workspace directory.
        backup: Path to the backup file, or None.
    """
    agents_md = workspace / "AGENTS.md"
    if agents_md.exists():
        agents_md.unlink()
    if backup is not None and backup.exists():
        backup.rename(agents_md)


def validate_onboarding_output(workspace: Path) -> bool:
    """Check that the agent generated valid workspace files.

    Args:
        workspace: Workspace root directory.

    Returns:
        True when all required files exist and contain valid YAML.
    """
    required = [
        workspace / _OBJECTIVE_FILENAME,
        workspace / _PROFILES_DIR / _PROFILES_FILENAME,
    ]
    for path in required:
        if not path.exists():
            return False
        try:
            content = yaml.safe_load(path.read_text(encoding=TEXT_ENCODING))
            if not isinstance(content, dict):
                return False
        except yaml.YAMLError:
            return False
    return True
