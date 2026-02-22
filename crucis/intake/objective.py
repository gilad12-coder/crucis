"""Parse objective YAML files into strict ParsedObjective models."""

import re
from pathlib import Path

import yaml

from crucis.defaults import TEXT_ENCODING
from crucis.intake.constants import HOLDOUT_EVALS_KEY, NAME_KEY, TRAIN_EVALS_KEY
from crucis.models import ParsedObjective, validate_holdout_eval_entries

_LEGACY_OBJECTIVE_KEYS = {"examples", "public_evals", "hidden_evals", "functions"}
_LEGACY_TASK_KEYS = {"examples", "public_evals", "hidden_evals"}
_MIGRATE_HINT = "crucis migrate --objective-in ... --objective-out ..."
_VALID_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_TARGET_FILES_KEY = "target_files"
_TASKS_KEY = "tasks"
_LEGACY_CONSTRAINT_PROFILE_KEY = "constraint_profile"
_TESTS_CONSTRAINT_PROFILE_KEY = "tests_constraint_profile"


def parse_objective(objective_path: Path) -> ParsedObjective:
    """Parse a YAML objective file and return a ParsedObjective model.

    Args:
        objective_path: Path to the objective YAML file.

    Returns:
        Parsed structured value.
    """
    data = yaml.safe_load(objective_path.read_text(encoding=TEXT_ENCODING))
    if not data:
        raise ValueError("Objective file is empty")
    if not isinstance(data, dict):
        raise ValueError("Objective file must contain a top-level mapping")

    _assert_no_legacy_objective_keys(data)
    _assert_no_legacy_task_keys(data)
    _migrate_constraint_profile_field(data)
    _assert_valid_objective_shape(data)
    _assert_valid_eval_entries(data)

    return ParsedObjective(**data)


def _assert_no_legacy_objective_keys(data: dict) -> None:
    """assert no legacy objective keys.

    Args:
        data: Dictionary payload being validated or migrated.
    """
    legacy = sorted(_LEGACY_OBJECTIVE_KEYS.intersection(data.keys()))
    if legacy:
        raise ValueError(
            "Legacy objective keys are not supported in runtime parsing: "
            f"{legacy}. Migrate first with `{_MIGRATE_HINT}`."
        )


def _assert_no_legacy_task_keys(data: dict) -> None:
    """assert no legacy task keys.

    Args:
        data: Dictionary payload being validated or migrated.
    """
    tasks = data.get(_TASKS_KEY) or []
    if not isinstance(tasks, list):
        raise ValueError("Objective field `tasks` must be a list")
    for idx, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ValueError(f"{_TASKS_KEY}[{idx}] must be a mapping")
        legacy = sorted(_LEGACY_TASK_KEYS.intersection(task.keys()))
        if legacy:
            raise ValueError(
                "Legacy task keys are not supported in runtime parsing: "
                f"{_TASKS_KEY}[{idx}] has {legacy}. Migrate first with `{_MIGRATE_HINT}`."
            )


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
        if not isinstance(item["input"], str) or not isinstance(item["output"], str):
            raise ValueError(f"{owner}[{idx}] input/output must be strings")


def _assert_valid_eval_entries(data: dict) -> None:
    """assert valid eval entries.

    Args:
        data: Dictionary payload being validated or migrated.
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


def _migrate_constraint_profile_field(data: dict) -> None:
    """Map legacy ``constraint_profile`` to ``tests_constraint_profile`` in-place.

    Args:
        data: Dictionary payload being validated or migrated.
    """
    if _LEGACY_CONSTRAINT_PROFILE_KEY in data:
        data.setdefault(_TESTS_CONSTRAINT_PROFILE_KEY, data.pop(_LEGACY_CONSTRAINT_PROFILE_KEY))
    for task in data.get(_TASKS_KEY) or []:
        if isinstance(task, dict) and _LEGACY_CONSTRAINT_PROFILE_KEY in task:
            task.setdefault(_TESTS_CONSTRAINT_PROFILE_KEY, task.pop(_LEGACY_CONSTRAINT_PROFILE_KEY))


def _assert_valid_objective_shape(data: dict) -> None:
    """assert valid objective shape.

    Args:
        data: Dictionary payload being validated or migrated.
    """
    raw_granularity = data.get("verification_granularity")
    if raw_granularity is not None and raw_granularity not in {"task", "objective"}:
        raise ValueError(
            "Objective field `verification_granularity` must be one of: " "`task`, `objective`."
        )

    _validate_callable_name(data.get(NAME_KEY), NAME_KEY)
    _validate_target_files(data.get(_TARGET_FILES_KEY), _TARGET_FILES_KEY)

    tasks = data.get(_TASKS_KEY) or []
    for idx, task in enumerate(tasks):
        _validate_callable_name(task.get(NAME_KEY), f"{_TASKS_KEY}[{idx}].{NAME_KEY}")
        target_files = task.get(_TARGET_FILES_KEY)
        _validate_target_files(target_files, f"{_TASKS_KEY}[{idx}].{_TARGET_FILES_KEY}")


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
