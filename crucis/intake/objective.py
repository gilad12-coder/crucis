"""Parse objective YAML files into strict ParsedObjective models."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from json_repair import repair_json
from pydantic import ValidationError

from crucis.cli.runner import run_cli_agent
from crucis.defaults import TEXT_ENCODING
from crucis.intake.constants import (
    EXAMPLES_KEY,
    HOLDOUT_EVALS_KEY,
    HOLDOUT_KEY,
    NAME_KEY,
    TRAIN_EVALS_KEY,
)
from crucis.models import ParsedObjective, validate_holdout_eval_entries
from crucis.prompts import render

_VALID_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_TARGET_FILES_KEY = "target_files"
_CONTEXT_FILES_KEY = "context_files"
_EXISTING_TESTS_KEY = "existing_tests"
_TASKS_KEY = "tasks"


_FIELD_ALIASES = {
    EXAMPLES_KEY: TRAIN_EVALS_KEY,
    HOLDOUT_KEY: HOLDOUT_EVALS_KEY,
}


def _normalize_field_aliases(data: dict) -> None:
    """Rewrite user-facing field aliases to internal canonical names.

    Mutates *data* in place. Accepts both ``examples`` and ``train_evals``
    (and ``holdout`` / ``holdout_evals``).  If both the alias and the
    canonical key are present, raises ``ValueError``.

    Args:
        data: Raw YAML mapping to normalize.
    """
    for alias, canonical in _FIELD_ALIASES.items():
        if alias in data:
            if canonical in data:
                raise ValueError(
                    f"Objective contains both `{alias}` and `{canonical}` — use one or the other"
                )
            data[canonical] = data.pop(alias)
    for task in data.get(_TASKS_KEY) or []:
        if isinstance(task, dict):
            for alias, canonical in _FIELD_ALIASES.items():
                if alias in task:
                    if canonical in task:
                        raise ValueError(
                            f"Task contains both `{alias}` and `{canonical}` — use one or the other"
                        )
                    task[canonical] = task.pop(alias)


def parse_objective(objective_path: Path) -> ParsedObjective:
    """Parse a YAML objective file and return a ParsedObjective model.

    Args:
        objective_path: Path to the objective YAML file.

    Returns:
        Parsed structured value.
    """
    try:
        raw = objective_path.read_text(encoding=TEXT_ENCODING)
    except FileNotFoundError:
        raise ValueError(f"Objective file not found: {objective_path}") from None
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"Could not parse YAML in {objective_path}: {exc}") from None
    if not data:
        raise ValueError("Objective file is empty")
    if not isinstance(data, dict):
        raise ValueError("Objective file must contain a top-level mapping")

    _normalize_field_aliases(data)
    _assert_valid_objective_shape(data)
    _assert_valid_eval_entries(data)

    try:
        return ParsedObjective(**data)
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise ValueError(f"Invalid objective: {errors}") from None



def _validate_train_eval_entries(eval_entries: list[dict], owner: str) -> None:
    """validate train eval entries.

    Args:
        eval_entries: Evaluation entries loaded from objective YAML.
        owner: Owner path used for validation error messages.
    """
    for idx, item in enumerate(eval_entries):
        if not isinstance(item, dict):
            raise ValueError(f"{owner}[{idx}] must be a mapping")
        if "raw" in item:
            raise ValueError(f"{owner}[{idx}] does not support raw")
        if "input" not in item or "output" not in item:
            raise ValueError(f"{owner}[{idx}] must contain both input and output")
        for field in ("input", "output"):
            val = item[field]
            if not isinstance(val, str):
                raise ValueError(
                    f"{owner}[{idx}] {field} must be a string, "
                    f"got {type(val).__name__}({val!r}) — wrap in quotes"
                )


def _assert_valid_eval_entries(data: dict) -> None:
    """assert valid eval entries.

    Args:
        data: Dictionary payload being validated.
    """
    train_evals = data.get(TRAIN_EVALS_KEY) or []
    holdout_evals = data.get(HOLDOUT_EVALS_KEY) or []
    _validate_train_eval_entries(train_evals, TRAIN_EVALS_KEY)
    validate_holdout_eval_entries(holdout_evals, HOLDOUT_EVALS_KEY)

    for idx, task in enumerate(data.get(_TASKS_KEY) or []):
        task_train = task.get(TRAIN_EVALS_KEY) or []
        task_holdout = task.get(HOLDOUT_EVALS_KEY) or []
        _validate_train_eval_entries(task_train, f"{_TASKS_KEY}[{idx}].{TRAIN_EVALS_KEY}")
        validate_holdout_eval_entries(task_holdout, f"{_TASKS_KEY}[{idx}].{HOLDOUT_EVALS_KEY}")



def _assert_valid_objective_shape(data: dict) -> None:
    """assert valid objective shape.

    Args:
        data: Dictionary payload being validated.
    """
    raw_granularity = data.get("verification_granularity")
    if raw_granularity is not None and raw_granularity not in {"task", "objective"}:
        raise ValueError(
            "Objective field `verification_granularity` must be one of: " "`task`, `objective`."
        )

    _validate_callable_name(data.get(NAME_KEY), NAME_KEY)
    _validate_target_files(data.get(_TARGET_FILES_KEY), _TARGET_FILES_KEY)
    _validate_relative_paths(data.get(_CONTEXT_FILES_KEY), _CONTEXT_FILES_KEY)
    _validate_target_files(data.get(_EXISTING_TESTS_KEY), _EXISTING_TESTS_KEY)

    tasks = data.get(_TASKS_KEY) or []
    seen_names: set[str] = set()
    for idx, task in enumerate(tasks):
        _validate_callable_name(task.get(NAME_KEY), f"{_TASKS_KEY}[{idx}].{NAME_KEY}")
        task_name = task.get(NAME_KEY)
        if task_name in seen_names:
            raise ValueError(f"Duplicate task name '{task_name}' at {_TASKS_KEY}[{idx}]")
        seen_names.add(task_name)
        _validate_target_files(task.get(_TARGET_FILES_KEY), f"{_TASKS_KEY}[{idx}].{_TARGET_FILES_KEY}")
        _validate_relative_paths(task.get(_CONTEXT_FILES_KEY), f"{_TASKS_KEY}[{idx}].{_CONTEXT_FILES_KEY}")
        _validate_target_files(task.get(_EXISTING_TESTS_KEY), f"{_TASKS_KEY}[{idx}].{_EXISTING_TESTS_KEY}")


def _validate_callable_name(name: object, owner: str) -> None:
    """Validate that objective/task names are safe Python identifiers.

    Args:
        name: Name value to validate.
        owner: Field path used for error messages.
    """
    if not isinstance(name, str) or not name:
        raise ValueError(f"{owner} must be a non-empty string")
    if not _VALID_IDENTIFIER_RE.fullmatch(name):
        raise ValueError(
            f"{owner} must be a valid Python identifier "
            "(letters, numbers, underscore; cannot start with a digit)"
        )


def _validate_relative_paths(paths: object, owner: str) -> None:
    """Validate paths as workspace-relative with no traversal segments.

    Args:
        paths: Raw path list from objective YAML.
        owner: Field path used for error messages.
    """
    if paths is None:
        return
    if not isinstance(paths, list) or any(not isinstance(item, str) for item in paths):
        raise ValueError(f"{owner} must be a list of strings")
    for idx, raw in enumerate(paths):
        value = raw.strip()
        if not value:
            raise ValueError(f"{owner}[{idx}] must be a non-empty path")
        normalized = value.replace("\\", "/")
        path = Path(normalized)
        if path.is_absolute():
            raise ValueError(f"{owner}[{idx}] must be workspace-relative, not absolute")
        if any(part in {"..", "."} for part in path.parts):
            raise ValueError(f"{owner}[{idx}] must not contain '.' or '..' path segments")


def _validate_target_files(target_files: object, owner: str) -> None:
    """Validate `target_files` as workspace-local Python source paths.

    Args:
        target_files: Raw `target_files` value from objective YAML.
        owner: Field path used for error messages.
    """
    if target_files is None:
        return
    if not isinstance(target_files, list) or any(
        not isinstance(item, str) for item in target_files
    ):
        raise ValueError(f"{owner} must be a list of strings")

    for idx, raw in enumerate(target_files):
        value = raw.strip()
        if not value:
            raise ValueError(f"{owner}[{idx}] must be a non-empty path")
        normalized = value.replace("\\", "/")
        path = Path(normalized)
        if path.is_absolute():
            raise ValueError(f"{owner}[{idx}] must be workspace-relative, not absolute")
        if any(part in {"..", "."} for part in path.parts):
            raise ValueError(f"{owner}[{idx}] must not contain '.' or '..' path segments")
        if path.suffix != ".py":
            raise ValueError(f"{owner}[{idx}] must point to a .py file")


def review_objective_semantics(
    objective: ParsedObjective,
    agent: str,
    model: str,
    budget: float,
) -> list[dict]:
    """Ask an LLM to verify eval expected values against the objective description.

    Args:
        objective: Parsed objective to review.
        agent: Agent binary name (e.g. "claude").
        model: Model identifier to use.
        budget: Max budget in USD for the agent call.

    Returns:
        List of issue dicts, each with keys: severity, eval_type, task,
        case_index, input, expected, explanation.
    """
    all_tasks = list(objective.tasks) if objective.tasks else []
    if not all_tasks:
        all_tasks = [objective]

    prompt = render("validate.jinja2", objective=objective, all_tasks=all_tasks)
    result = run_cli_agent(prompt, agent, model, budget)

    if result.exit_code != 0:
        raise RuntimeError(f"Validation agent failed: {result.stderr}")

    parsed = repair_json(result.stdout, return_objects=True)
    if isinstance(parsed, dict) and "issues" in parsed:
        return parsed["issues"]
    return []
