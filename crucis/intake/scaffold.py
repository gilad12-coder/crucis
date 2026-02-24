"""Workspace scaffolding for `crucis init`."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from crucis.defaults import TEXT_ENCODING

_OBJECTIVE_FILENAME = "objective.yaml"
_PROFILES_DIR = "constraints"
_PROFILES_FILENAME = "profiles.yaml"
_RECOMMENDED_PROFILE = "recommended"
_EXISTING_CODEBASE_SCAN_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
    }
)

_SETTINGS_TEMPLATE = """\
schema_version: 1

# Background optimizer (optional — requires an API key for the reflection_lm provider).
# The optimizer refines generation prompts after each fit run.
optimizer:
  enabled: false
  reflection_lm: openai/gpt-5.2
  reflection_api_key: null
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
# Model defaults per agent:
#   claude -> claude-opus-4-6
#   codex  -> (uses codex built-in default; set model to null)
agents:
  generation_agent: null
  generation_model: null
  critic_agent: null
  critic_model: null
  implementation_agent: null
  implementation_model: null
  api_key: null
  max_iterations: null
  max_budget_usd: null
"""

_AGENTS = ["claude", "codex"]

_AGENT_MODELS: dict[str, list[str]] = {
    "claude": ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
    "codex": ["o4-mini", "o3"],
}

_CHOICE_PROMPT = "Choice [1]: "


def prompt_model_selection() -> tuple[str | None, str | None]:
    """Interactively ask the user to pick an agent and model.

    Returns:
        Tuple of (agent, model), or (None, None) when non-interactive.
    """
    if not sys.stdin.isatty():
        return None, None

    print("\nConfigure agent and model for this workspace.")
    print("\nWhich agent?")
    for i, name in enumerate(_AGENTS, 1):
        suffix = " (default)" if i == 1 else ""
        print(f"  {i}. {name}{suffix}")
    agent = _read_choice(_AGENTS)

    models = _AGENT_MODELS[agent]
    print(f"\nWhich model? ({agent})")
    for i, name in enumerate(models, 1):
        suffix = " (default)" if i == 1 else ""
        print(f"  {i}. {name}{suffix}")
    model = _read_choice(models)

    print(f"\nUsing {agent} with {model}\n")
    return agent, model


def _read_choice(options: list[str]) -> str:
    """Read a numbered choice from stdin, defaulting to the first option.

    Args:
        options: List of option strings.

    Returns:
        The selected option string.
    """
    from crucis.display import prompt_input

    raw = prompt_input(_CHOICE_PROMPT)
    if not raw:
        return options[0]
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx]
    except ValueError:
        pass
    return options[0]


def _render_settings_template(
    agent: str | None = None,
    model: str | None = None,
) -> str:
    """Render settings template with agent/model values substituted.

    Args:
        agent: Agent name to set for all agent fields, or None for null.
        model: Model name to set for all model fields, or None for null.

    Returns:
        Settings YAML string with values filled in.
    """
    text = _SETTINGS_TEMPLATE
    if agent is not None:
        agent_val = agent
        text = text.replace("generation_agent: null", f"generation_agent: {agent_val}")
        text = text.replace("critic_agent: null", f"critic_agent: {agent_val}")
        text = text.replace("implementation_agent: null", f"implementation_agent: {agent_val}")
    if model is not None:
        model_val = model
        text = text.replace("generation_model: null", f"generation_model: {model_val}")
        text = text.replace("critic_model: null", f"critic_model: {model_val}")
        text = text.replace("implementation_model: null", f"implementation_model: {model_val}")
    return text


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
                "examples": [
                    {"input": "(0,)", "output": "1"},
                    {"input": "(1,)", "output": "1"},
                    {"input": "(5,)", "output": "120"},
                    {"input": "(10,)", "output": "3628800"},
                ],
            }
        ],
    },
    "calculator": {
        "description": "Basic integer calculator with add, subtract, and multiply.",
        "tasks": [
            {
                "name": "add",
                "description": "Return the sum of two integers.",
                "signature": "add(a: int, b: int) -> int",
                "examples": [
                    {"input": "(1, 2)", "output": "3"},
                    {"input": "(0, 0)", "output": "0"},
                    {"input": "(-1, 1)", "output": "0"},
                ],
            },
            {
                "name": "subtract",
                "description": "Return the difference of two integers.",
                "signature": "subtract(a: int, b: int) -> int",
                "examples": [
                    {"input": "(5, 3)", "output": "2"},
                    {"input": "(0, 0)", "output": "0"},
                ],
            },
            {
                "name": "multiply",
                "description": "Return the product of two integers.",
                "signature": "multiply(a: int, b: int) -> int",
                "examples": [
                    {"input": "(3, 4)", "output": "12"},
                    {"input": "(0, 5)", "output": "0"},
                ],
            },
        ],
    },
}


def _build_existing_codebase_objective(name: str) -> dict:
    """Build objective scaffold for repositories that already contain source code.

    Args:
        name: Project name used for objective/task naming.

    Returns:
        Objective data dict oriented toward existing-file edits.
    """
    return {
        "name": name,
        "description": (
            "Define the behavior change you want in this existing codebase. "
            "Set target_files/context_files to real project modules."
        ),
        "tests_constraint_profile": _RECOMMENDED_PROFILE,
        "implementation_constraint_profile": "default",
        "target_files": [],
        "tasks": [
            {
                "name": name,
                "description": "Implement the requested behavior in existing project files.",
                "signature": None,
                "target_files": [],
                "context_files": [],
                "existing_tests": [],
                "examples": [{"input": "(...)", "output": "..."}],
                "holdout": [],
            }
        ],
    }


def _build_objective(name: str, existing_codebase: bool = False) -> dict:
    """Build an objective dict from a built-in template or generic fallback.

    Args:
        name: Project name (may match a built-in template key).
        existing_codebase: Whether scaffold should target an existing repository.

    Returns:
        Objective data dict ready for YAML serialization.
    """
    if existing_codebase:
        return _build_existing_codebase_objective(name)

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
        "description": f"Describe what {name} does.",
        "signature": f"{name}(x: Any) -> Any",
        "tests_constraint_profile": _RECOMMENDED_PROFILE,
        "implementation_constraint_profile": _RECOMMENDED_PROFILE,
        "target_files": ["src/solution.py"],
        "tasks": [
            {
                "name": name,
                "description": f"Implement {name}. Replace this with a real description.",
                "signature": f"{name}(x: Any) -> Any",
                "examples": [
                    {"input": "(1,)", "output": "1"},
                ],
                "holdout": [],
            }
        ],
    }


_DEFAULT_PROFILES = {
    "profiles": {
        "default": {
            "primary": {
                "max_cyclomatic_complexity": 10,
            },
            "secondary": {
                "require_docstrings": True,
            },
        },
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
            },
            "secondary": {
                "require_docstrings": True,
                "no_print_statements": True,
                "no_magic_numbers": True,
            },
        },
    },
    "functions": {},
}


def detect_existing_codebase(workspace: Path) -> bool:
    """Return True when workspace appears to already contain Python source files.

    Args:
        workspace: Workspace root directory to inspect.

    Returns:
        True when Python files are present outside ignored cache/tooling folders.
    """
    if not workspace.exists():
        return False
    for python_file in workspace.rglob("*.py"):
        if not python_file.is_file():
            continue
        if any(part in _EXISTING_CODEBASE_SCAN_SKIP_DIRS for part in python_file.parts):
            continue
        return True
    return False


def scaffold_workspace(
    workspace: Path,
    name: str = "my_project",
    existing_codebase: bool | None = None,
    agent: str | None = None,
    model: str | None = None,
) -> list[Path]:
    """Create starter files for a new Crucis workspace.

    Skips any file that already exists.

    Args:
        workspace: Workspace root directory.
        name: Project name used in the objective template.
        existing_codebase: Explicitly force existing-codebase scaffolding mode.
            When None, mode is auto-detected from existing Python files.
        agent: Agent name to write into settings.yaml, or None for null.
        model: Model name to write into settings.yaml, or None for null.

    Returns:
        List of file paths that were created.
    """
    created: list[Path] = []
    existing_mode = (
        detect_existing_codebase(workspace) if existing_codebase is None else existing_codebase
    )

    objective_data = _build_objective(name, existing_codebase=existing_mode)
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
        settings_file.write_text(_render_settings_template(agent, model), encoding=TEXT_ENCODING)
        created.append(settings_file)

    if not existing_mode:
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
    secondary:
      require_docstrings: true
      no_print_statements: true
      no_debugger_statements: true
      no_magic_numbers: true

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
context_files:          # optional: existing files injected into prompts for context
  - src/helpers.py
existing_tests:         # optional: test files run as a regression gate during evaluation
  - tests/test_existing.py
tasks:
  - name: <task_name>
    description: <what this task does>
    signature: <function_name(args) -> return_type>
    examples:
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
            exit_code, error_msg = run_interactive_agent(prompt, agent, model, cwd=workspace)
        finally:
            _restore_agents_md(workspace, backup)
    else:
        exit_code, error_msg = run_interactive_agent(prompt, agent, model, cwd=workspace)

    if exit_code != 0 and error_msg:
        from crucis.display import display_warning
        display_warning(error_msg)
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
