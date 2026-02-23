"""Migration utilities for legacy spec/session files to Crucis schema."""

import json
from pathlib import Path

import yaml

from crucis.defaults import TEXT_ENCODING
from crucis.intake.constants import (
    DESCRIPTION_KEY,
    HOLDOUT_EVALS_KEY,
    NAME_KEY,
    SIGNATURE_KEY,
    TASKS_KEY,
    TRAIN_EVALS_KEY,
)

_OLD_TO_NEW_STATUS = {
    "pending": "pending",
    "tests_generated": "train_suite_generated",
    "tests_approved": "train_suite_approved",
    "critiqued": "adversarially_reviewed",
    "done": "complete",
    "train_suite_generated": "train_suite_generated",
    "train_suite_approved": "train_suite_approved",
    "adversarially_reviewed": "adversarially_reviewed",
    "complete": "complete",
}


class _NoAliasSafeDumper(yaml.SafeDumper):
    """Safe dumper variant that disables YAML anchors and aliases."""

    def ignore_aliases(self, data: object) -> bool:
        return True


def migrate_objective_data(data: dict) -> dict:
    """Convert legacy/new objective data into strict new-schema objective data.

    Args:
        data: Dictionary payload being validated or migrated.

    Returns:
        Dictionary containing structured result data.
    """
    if not isinstance(data, dict):
        raise ValueError("Objective data must be a mapping")

    tests_cp = data.get("tests_constraint_profile", data.get("constraint_profile", "default"))
    impl_cp = data.get("implementation_constraint_profile", "default")
    output = {
        NAME_KEY: data.get(NAME_KEY),
        DESCRIPTION_KEY: data.get(DESCRIPTION_KEY),
        SIGNATURE_KEY: data.get(SIGNATURE_KEY),
        "tests_constraint_profile": tests_cp,
        "implementation_constraint_profile": impl_cp,
        "target_files": list(data.get("target_files") or []),
        "verification_granularity": data.get("verification_granularity", "task"),
    }

    output[TRAIN_EVALS_KEY] = _resolve_train_evals(data)
    output[HOLDOUT_EVALS_KEY] = _resolve_holdout_evals(data)
    output[TASKS_KEY] = [_migrate_task_data(task) for task in _resolve_tasks(data)]

    if not output[TASKS_KEY] and output.get(NAME_KEY):
        default_task: dict = {NAME_KEY: output[NAME_KEY]}
        for key in (DESCRIPTION_KEY, SIGNATURE_KEY, TRAIN_EVALS_KEY, HOLDOUT_EVALS_KEY):
            if output.get(key):
                default_task[key] = output[key]
        output[TASKS_KEY] = [default_task]

    return {k: v for k, v in output.items() if v is not None}


def _resolve_train_evals(data: dict) -> list[dict]:
    """resolve train evals.

    Args:
        data: Dictionary payload being validated or migrated.

    Returns:
        Dictionary containing structured result data.
    """
    if "public_evals" in data:
        return list(data.get("public_evals") or [])
    if "examples" in data:
        return list(data.get("examples") or [])
    return list(data.get(TRAIN_EVALS_KEY) or [])


def _resolve_holdout_evals(data: dict) -> list[dict]:
    """resolve holdout evals.

    Args:
        data: Dictionary payload being validated or migrated.

    Returns:
        Dictionary containing structured result data.
    """
    if "hidden_evals" in data:
        return list(data.get("hidden_evals") or [])
    return list(data.get(HOLDOUT_EVALS_KEY) or [])


def _resolve_tasks(data: dict) -> list[dict]:
    """resolve tasks.

    Args:
        data: Dictionary payload being validated or migrated.

    Returns:
        Dictionary containing structured result data.
    """
    if "functions" in data:
        return list(data.get("functions") or [])
    return list(data.get(TASKS_KEY) or [])


def _migrate_task_data(task: dict) -> dict:
    """migrate task data.

    Args:
        task: Value for `task` used by `_migrate_task_data`.

    Returns:
        Dictionary containing structured result data.
    """
    if not isinstance(task, dict):
        raise ValueError("Task entries must be mappings")

    tests_cp = task.get("tests_constraint_profile", task.get("constraint_profile"))
    impl_cp = task.get("implementation_constraint_profile")
    output = {
        NAME_KEY: task.get(NAME_KEY),
        DESCRIPTION_KEY: task.get(DESCRIPTION_KEY, ""),
        SIGNATURE_KEY: task.get(SIGNATURE_KEY),
        "tests_constraint_profile": tests_cp,
        "implementation_constraint_profile": impl_cp,
        "target_files": list(task.get("target_files") or []),
    }

    output[TRAIN_EVALS_KEY] = _resolve_train_evals(task)
    output[HOLDOUT_EVALS_KEY] = _resolve_holdout_evals(task)

    return {k: v for k, v in output.items() if v is not None}


def migrate_objective_file(objective_in: Path, objective_out: Path) -> None:
    """Read objective yaml and write migrated new-schema objective yaml.

    Args:
        objective_in: Input objective path to migrate.
        objective_out: Output path for migrated objective YAML.
    """
    try:
        raw = objective_in.read_text(encoding=TEXT_ENCODING)
    except FileNotFoundError:
        raise ValueError(f"Objective file not found: {objective_in}") from None
    except OSError as exc:
        raise ValueError(f"Could not read objective file {objective_in}: {exc}") from None

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"Could not parse YAML in {objective_in}: {exc}") from None
    if data is None:
        raise ValueError("Objective file is empty")
    if not isinstance(data, dict):
        raise ValueError("Objective file must contain a top-level mapping")

    migrated = migrate_objective_data(data)
    try:
        objective_out.write_text(
            yaml.dump(migrated, sort_keys=False, Dumper=_NoAliasSafeDumper),
            encoding=TEXT_ENCODING,
        )
    except OSError as exc:
        raise ValueError(f"Could not write migrated objective file {objective_out}: {exc}") from None


def migrate_checkpoint_data(data: dict) -> dict:
    """Convert legacy/new checkpoint data into strict new-schema checkpoint data.

    Args:
        data: Dictionary payload being validated or migrated.

    Returns:
        Dictionary containing structured result data.
    """
    if not isinstance(data, dict):
        raise ValueError("Checkpoint data must be a mapping")

    raw_progress = data.get("function_progress")
    if raw_progress is None:
        raw_progress = data.get("task_progress")
    if raw_progress is None:
        raw_progress = []

    if not isinstance(raw_progress, list):
        raise ValueError("Checkpoint progress must be a list")

    return {"task_progress": [_migrate_progress_item(item) for item in raw_progress]}


def _migrate_progress_item(item: dict) -> dict:
    """migrate progress item.

    Args:
        item: Progress item from checkpoint to migrate.

    Returns:
        Dictionary containing structured result data.
    """
    if not isinstance(item, dict):
        raise ValueError("Checkpoint progress entries must be mappings")

    status = item.get("status", "pending")
    mapped_status = _OLD_TO_NEW_STATUS.get(status)
    if mapped_status is None:
        raise ValueError(f"Unknown status value: {status}")

    report = item.get("critique")
    if report is None:
        report = item.get("adversarial_report")

    output = {
        "name": item.get(NAME_KEY),
        "status": mapped_status,
        "train_suite_source": item.get("test_source", item.get("train_suite_source")),
        "adversarial_report": _migrate_report(report) if report else None,
    }
    return {k: v for k, v in output.items() if v is not None}


def _migrate_report(report: dict) -> dict:
    """migrate report.

    Args:
        report: Adversarial report payload for the current task.

    Returns:
        Dictionary containing structured result data.
    """
    if not isinstance(report, dict):
        raise ValueError("Adversarial report must be a mapping")

    output = {
        "attack_vectors": list(report.get("attack_vectors", report.get("exploit_vectors", []))),
        "generalization_gaps": list(
            report.get("generalization_gaps", report.get("missing_edge_cases", []))
        ),
        "suggested_probe_tests": list(
            report.get("suggested_probe_tests", report.get("suggested_counter_tests", []))
        ),
        "probe_code": report.get("probe_code", report.get("exploit_code")),
        "probe_succeeded": bool(
            report.get("probe_succeeded", report.get("exploit_passed", False))
        ),
    }
    return output


def migrate_checkpoint_file(checkpoint_in: Path, checkpoint_out: Path) -> None:
    """Read checkpoint json and write migrated new-schema checkpoint json.

    Args:
        checkpoint_in: Input checkpoint path to migrate.
        checkpoint_out: Output path for migrated checkpoint JSON.
    """
    try:
        raw = checkpoint_in.read_text(encoding=TEXT_ENCODING)
    except FileNotFoundError:
        raise ValueError(f"Checkpoint file not found: {checkpoint_in}") from None
    except OSError as exc:
        raise ValueError(f"Could not read checkpoint file {checkpoint_in}: {exc}") from None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse JSON in {checkpoint_in}: {exc}") from None

    migrated = migrate_checkpoint_data(data)
    try:
        checkpoint_out.write_text(json.dumps(migrated, indent=2), encoding=TEXT_ENCODING)
    except OSError as exc:
        raise ValueError(f"Could not write migrated checkpoint file {checkpoint_out}: {exc}") from None
