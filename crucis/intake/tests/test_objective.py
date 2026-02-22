"""Tests for strict objective parser behavior."""

from pathlib import Path

import pytest
import yaml

from crucis.intake.objective import parse_objective


def _write(path: Path, data: dict) -> Path:
    """write.

    Args:
        path: Filesystem path used by the current operation.
        data: Dictionary payload being validated or migrated.

    Returns:
        Resolved filesystem path for this operation.
    """
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_parse_objective_with_new_schema(tmp_path):
    """Parser should accept strict new objective schema keys.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective_file = _write(
        tmp_path / "objective.yaml",
        {
            "name": "add",
            "description": "Add two numbers",
            "train_evals": [{"input": "(1, 2)", "output": "3"}],
            "holdout_evals": [{"input": "(10, 20)", "output": "30"}],
            "verification_granularity": "task",
            "tasks": [
                {
                    "name": "add",
                    "train_evals": [{"input": "(2, 3)", "output": "5"}],
                    "target_files": ["src/add.py"],
                }
            ],
        },
    )
    result = parse_objective(objective_file)
    assert result.name == "add"
    assert result.train_evals[0].input == "(1, 2)"
    assert result.holdout_evals[0].input == "(10, 20)"
    assert result.tasks[0].name == "add"
    assert result.tasks[0].target_files == ["src/add.py"]


def test_parse_objective_rejects_legacy_top_level_keys(tmp_path):
    """Legacy keys should fail fast with migration guidance.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective_file = _write(
        tmp_path / "objective.yaml",
        {
            "name": "add",
            "description": "Add",
            "examples": [{"input": "(1, 2)", "output": "3"}],
        },
    )
    with pytest.raises(ValueError) as exc:
        parse_objective(objective_file)
    assert "crucis migrate --objective-in ... --objective-out ..." in str(exc.value)


def test_parse_objective_rejects_legacy_task_keys(tmp_path):
    """Legacy task keys should also fail fast with migration guidance.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective_file = _write(
        tmp_path / "objective.yaml",
        {
            "name": "add",
            "description": "Add",
            "tasks": [
                {
                    "name": "add",
                    "public_evals": [{"input": "(1, 2)", "output": "3"}],
                }
            ],
        },
    )
    with pytest.raises(ValueError) as exc:
        parse_objective(objective_file)
    assert "crucis migrate --objective-in ... --objective-out ..." in str(exc.value)


def test_parse_objective_rejects_invalid_holdout_expression(tmp_path):
    """Holdout syntax errors should fail during parsing, not runtime eval.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective_file = _write(
        tmp_path / "objective.yaml",
        {
            "name": "add",
            "description": "Add",
            "holdout_evals": [{"input": "(1, 2", "output": "3"}],
        },
    )
    with pytest.raises(ValueError):
        parse_objective(objective_file)


def test_parse_objective_rejects_invalid_verification_granularity(tmp_path):
    """Unsupported verification granularity should fail fast.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective_file = _write(
        tmp_path / "objective.yaml",
        {
            "name": "add",
            "description": "Add",
            "verification_granularity": "suite",
        },
    )
    with pytest.raises(ValueError) as exc:
        parse_objective(objective_file)
    assert "verification_granularity" in str(exc.value)


def test_parse_objective_rejects_invalid_task_target_files(tmp_path):
    """Task target files must be a list of strings.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective_file = _write(
        tmp_path / "objective.yaml",
        {
            "name": "add",
            "description": "Add",
            "tasks": [{"name": "add", "target_files": [1, 2]}],
        },
    )
    with pytest.raises(ValueError) as exc:
        parse_objective(objective_file)
    assert "tasks[0].target_files" in str(exc.value)


def test_parse_objective_empty_file_raises(tmp_path):
    """Empty objective files should raise ValueError.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective_file = tmp_path / "objective.yaml"
    objective_file.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_objective(objective_file)


def test_parse_objective_rejects_invalid_objective_name(tmp_path):
    """Objective name must be a safe Python identifier.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective_file = _write(
        tmp_path / "objective.yaml",
        {
            "name": "bad-name",
            "description": "Add",
        },
    )
    with pytest.raises(ValueError) as exc:
        parse_objective(objective_file)
    assert "name must be a valid Python identifier" in str(exc.value)


def test_parse_objective_rejects_invalid_task_name(tmp_path):
    """Task names must be safe Python identifiers.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective_file = _write(
        tmp_path / "objective.yaml",
        {
            "name": "add",
            "description": "Add",
            "tasks": [{"name": "task-1"}],
        },
    )
    with pytest.raises(ValueError) as exc:
        parse_objective(objective_file)
    assert "tasks[0].name must be a valid Python identifier" in str(exc.value)


def test_parse_objective_rejects_absolute_target_file(tmp_path):
    """Target files must be workspace-relative paths.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective_file = _write(
        tmp_path / "objective.yaml",
        {
            "name": "add",
            "description": "Add",
            "target_files": ["/tmp/add.py"],
        },
    )
    with pytest.raises(ValueError) as exc:
        parse_objective(objective_file)
    assert "workspace-relative" in str(exc.value)


def test_parse_objective_rejects_target_file_with_parent_segment(tmp_path):
    """Target files must not include traversal segments.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective_file = _write(
        tmp_path / "objective.yaml",
        {
            "name": "add",
            "description": "Add",
            "target_files": ["src/../add.py"],
        },
    )
    with pytest.raises(ValueError) as exc:
        parse_objective(objective_file)
    assert "must not contain '.' or '..'" in str(exc.value)


def test_parse_objective_rejects_non_python_target_file(tmp_path):
    """Target files must point to Python source files.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective_file = _write(
        tmp_path / "objective.yaml",
        {
            "name": "add",
            "description": "Add",
            "tasks": [{"name": "add", "target_files": ["src/add.txt"]}],
        },
    )
    with pytest.raises(ValueError) as exc:
        parse_objective(objective_file)
    assert "tasks[0].target_files[0] must point to a .py file" in str(exc.value)


def test_parse_objective_migrates_legacy_constraint_profile(tmp_path):
    """Legacy constraint_profile should map to tests_constraint_profile.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective_file = _write(
        tmp_path / "objective.yaml",
        {
            "name": "add",
            "description": "Add",
            "constraint_profile": "strict",
        },
    )
    result = parse_objective(objective_file)
    assert result.tests_constraint_profile == "strict"
    assert result.implementation_constraint_profile == "default"


def test_parse_objective_migrates_legacy_task_constraint_profile(tmp_path):
    """Legacy task-level constraint_profile should map to tests_constraint_profile.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective_file = _write(
        tmp_path / "objective.yaml",
        {
            "name": "add",
            "description": "Add",
            "tasks": [
                {
                    "name": "add",
                    "constraint_profile": "strict",
                }
            ],
        },
    )
    result = parse_objective(objective_file)
    assert result.tasks[0].tests_constraint_profile == "strict"
    assert result.tasks[0].implementation_constraint_profile is None


def test_parse_objective_accepts_new_constraint_profile_fields(tmp_path):
    """New tests_constraint_profile and implementation_constraint_profile should parse.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective_file = _write(
        tmp_path / "objective.yaml",
        {
            "name": "add",
            "description": "Add",
            "tests_constraint_profile": "strict",
            "implementation_constraint_profile": "recommended",
            "tasks": [
                {
                    "name": "add",
                    "tests_constraint_profile": "default",
                    "implementation_constraint_profile": "strict",
                }
            ],
        },
    )
    result = parse_objective(objective_file)
    assert result.tests_constraint_profile == "strict"
    assert result.implementation_constraint_profile == "recommended"
    assert result.tasks[0].tests_constraint_profile == "default"
    assert result.tasks[0].implementation_constraint_profile == "strict"
