"""Tests for profile loading and constraint resolution."""

from pathlib import Path

import pytest
import yaml

from crucis.constraints.loader import (
    _normalize_profile_data,
    extract_custom_checks,
    load_profiles,
    resolve_constraints,
)
from crucis.models import ParsedObjective, TaskObjective

PROFILES = {
    "profiles": {
        "default": {
            "primary": {"max_cyclomatic_complexity": 10},
            "secondary": {"require_docstrings": False},
            "guidance": ["keep it simple"],
        },
        "strict": {
            "primary": {"max_cyclomatic_complexity": 5},
            "secondary": {"require_docstrings": True},
            "guidance": ["be explicit"],
        },
    },
    "tasks": {
        "login": {
            "primary": {"max_lines_per_function": 20},
            "guidance": ["validate auth edge cases"],
        }
    },
}


def _write_profiles(tmp_path: Path) -> Path:
    """write profiles.

    Args:
        tmp_path: Temporary directory provided by pytest.

    Returns:
        Resolved filesystem path for this operation.
    """
    path = tmp_path / "profiles.yaml"
    path.write_text(yaml.safe_dump(PROFILES), encoding="utf-8")
    return path


def test_load_profiles_returns_flat_map(tmp_path):
    """Load profiles and expose top-level names + tasks map.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    profiles = load_profiles(_write_profiles(tmp_path))
    assert "default" in profiles
    assert "strict" in profiles
    assert "tasks" in profiles


def test_resolve_constraints_uses_task_profile_override(tmp_path):
    """Task-level objective profile should override top-level profile.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    profiles = load_profiles(_write_profiles(tmp_path))
    objective = ParsedObjective(
        name="auth",
        description="Auth task",
        tests_constraint_profile="default",
        target_files=["src/auth.py"],
        tasks=[
            TaskObjective(name="login", tests_constraint_profile="strict"),
            TaskObjective(name="logout"),
        ],
    )

    login = resolve_constraints(objective, profiles, task_name="login")
    logout = resolve_constraints(objective, profiles, task_name="logout")

    assert login.primary.max_cyclomatic_complexity == 5
    assert logout.primary.max_cyclomatic_complexity == 10


def test_resolve_constraints_applies_task_overrides(tmp_path):
    """Profile task overrides should merge into resolved constraints.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    profiles = load_profiles(_write_profiles(tmp_path))
    objective = ParsedObjective(
        name="auth",
        description="Auth task",
        tests_constraint_profile="default",
        target_files=["src/auth.py"],
    )

    resolved = resolve_constraints(objective, profiles, task_name="login")
    assert resolved.primary.max_lines_per_function == 20
    assert resolved.guidance == ["validate auth edge cases"]


def test_resolve_constraints_prefers_task_target_files_when_present(tmp_path):
    """Task-level target files should override objective-level target files.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    profiles = load_profiles(_write_profiles(tmp_path))
    objective = ParsedObjective(
        name="auth",
        description="Auth task",
        tests_constraint_profile="default",
        target_files=["src/auth.py"],
        tasks=[TaskObjective(name="login", target_files=["src/login.py"])],
    )

    resolved = resolve_constraints(objective, profiles, task_name="login")
    assert resolved.target_files == ["src/login.py"]


def test_resolve_constraints_falls_back_to_objective_target_files(tmp_path):
    """Objective target files should be used when task target files are absent.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    profiles = load_profiles(_write_profiles(tmp_path))
    objective = ParsedObjective(
        name="auth",
        description="Auth task",
        tests_constraint_profile="default",
        target_files=["src/auth.py"],
        tasks=[TaskObjective(name="logout")],
    )

    resolved = resolve_constraints(objective, profiles, task_name="logout")
    assert resolved.target_files == ["src/auth.py"]


def test_resolve_constraints_scope_tests_uses_tests_profile(tmp_path):
    """Scope 'tests' should read tests_constraint_profile field.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    profiles = load_profiles(_write_profiles(tmp_path))
    objective = ParsedObjective(
        name="auth",
        description="Auth task",
        tests_constraint_profile="strict",
        implementation_constraint_profile="default",
        target_files=["src/auth.py"],
    )

    resolved = resolve_constraints(objective, profiles, scope="tests")
    assert resolved.primary.max_cyclomatic_complexity == 5


def test_resolve_constraints_scope_implementation_uses_impl_profile(tmp_path):
    """Scope 'implementation' should read implementation_constraint_profile field.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    profiles = load_profiles(_write_profiles(tmp_path))
    objective = ParsedObjective(
        name="auth",
        description="Auth task",
        tests_constraint_profile="strict",
        implementation_constraint_profile="default",
        target_files=["src/auth.py"],
    )

    resolved = resolve_constraints(objective, profiles, scope="implementation")
    assert resolved.primary.max_cyclomatic_complexity == 10


def test_resolve_constraints_task_override_per_scope(tmp_path):
    """Task-level profile overrides should work independently per scope.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    profiles = load_profiles(_write_profiles(tmp_path))
    objective = ParsedObjective(
        name="auth",
        description="Auth task",
        tests_constraint_profile="default",
        implementation_constraint_profile="default",
        target_files=["src/auth.py"],
        tasks=[
            TaskObjective(
                name="login",
                tests_constraint_profile="strict",
                implementation_constraint_profile="default",
            ),
        ],
    )

    test_resolved = resolve_constraints(objective, profiles, task_name="login", scope="tests")
    impl_resolved = resolve_constraints(
        objective, profiles, task_name="login", scope="implementation"
    )

    assert test_resolved.primary.max_cyclomatic_complexity == 5
    assert impl_resolved.primary.max_cyclomatic_complexity == 10


def test_load_profiles_missing_file_returns_defaults(tmp_path):
    """Missing profiles file should return built-in default profiles.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    profiles = load_profiles(tmp_path / "nonexistent.yaml")
    assert "recommended" in profiles
    assert "default" in profiles


def test_load_profiles_malformed_yaml_raises_valueerror(tmp_path):
    """Malformed YAML in profiles should raise ValueError.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    bad = tmp_path / "profiles.yaml"
    bad.write_text("profiles: [invalid: yaml: {{", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_profiles(bad)
    assert "Could not parse YAML" in str(exc.value)


def test_resolve_constraints_unknown_profile_lists_available(tmp_path):
    """Unknown profile error should list available profile names.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    profiles = load_profiles(_write_profiles(tmp_path))
    objective = ParsedObjective(
        name="auth",
        description="Auth task",
        tests_constraint_profile="nonexistent",
        target_files=["src/auth.py"],
    )
    with pytest.raises(ValueError) as exc:
        resolve_constraints(objective, profiles, scope="tests")
    msg = str(exc.value)
    assert "nonexistent" in msg
    assert "default" in msg
    assert "strict" in msg


# ---------------------------------------------------------------------------
# extract_custom_checks
# ---------------------------------------------------------------------------

PROFILES_WITH_CUSTOM = {
    "profiles": {
        "default": {
            "primary": {"max_cyclomatic_complexity": 10},
            "secondary": {"require_docstrings": False},
            "custom_checks": {
                "primary": {"no_todo": True},
                "secondary": {"max_imports": 5},
            },
        },
        "plain": {
            "primary": {"max_cyclomatic_complexity": 10},
        },
    },
}


def _write_custom_profiles(tmp_path: Path) -> Path:
    """Write profiles with custom_checks to a temp YAML file.

    Args:
        tmp_path: Temporary directory provided by pytest.

    Returns:
        Path to the written profiles file.
    """
    path = tmp_path / "profiles.yaml"
    path.write_text(yaml.safe_dump(PROFILES_WITH_CUSTOM), encoding="utf-8")
    return path


def test_extract_custom_checks_returns_config(tmp_path):
    """extract_custom_checks should return the custom_checks dict when present.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    profiles = load_profiles(_write_custom_profiles(tmp_path))
    objective = ParsedObjective(
        name="demo",
        description="Demo",
        tests_constraint_profile="default",
        target_files=["src/demo.py"],
    )
    result = extract_custom_checks(objective, profiles)
    assert result is not None
    assert result["primary"]["no_todo"] is True
    assert result["secondary"]["max_imports"] == 5


def test_extract_custom_checks_returns_none_when_absent(tmp_path):
    """extract_custom_checks should return None when profile has no custom_checks.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    profiles = load_profiles(_write_custom_profiles(tmp_path))
    objective = ParsedObjective(
        name="demo",
        description="Demo",
        tests_constraint_profile="plain",
        target_files=["src/demo.py"],
    )
    result = extract_custom_checks(objective, profiles)
    assert result is None


# ---------------------------------------------------------------------------
# Flat constraint format normalization
# ---------------------------------------------------------------------------

FLAT_PROFILES = {
    "profiles": {
        "default": {
            "max_cyclomatic_complexity": 10,
            "require_docstrings": True,
            "guidance": ["keep it simple"],
        },
    },
    "tasks": {},
}


def _write_flat_profiles(tmp_path: Path) -> Path:
    """Write flat-format profiles to a temp YAML file.

    Args:
        tmp_path: Temporary directory provided by pytest.

    Returns:
        Path to the written profiles file.
    """
    path = tmp_path / "profiles.yaml"
    path.write_text(yaml.safe_dump(FLAT_PROFILES), encoding="utf-8")
    return path


def test_normalize_splits_flat_fields():
    """Flat constraint fields should be split into primary and secondary."""
    data = {
        "max_cyclomatic_complexity": 10,
        "require_docstrings": True,
        "no_magic_numbers": True,
        "guidance": ["be clean"],
    }
    result = _normalize_profile_data(data)
    assert result["primary"]["max_cyclomatic_complexity"] == 10
    assert result["primary"]["no_magic_numbers"] is True
    assert result["secondary"]["require_docstrings"] is True
    assert result["guidance"] == ["be clean"]
    assert "max_cyclomatic_complexity" not in result["secondary"]
    assert "require_docstrings" not in result["primary"]


def test_normalize_passes_through_old_format():
    """Old primary/secondary format should pass through unchanged."""
    data = {
        "primary": {"max_cyclomatic_complexity": 10},
        "secondary": {"require_docstrings": True},
    }
    result = _normalize_profile_data(data)
    assert result is data


def test_resolve_constraints_flat_format(tmp_path):
    """Flat-format profiles should resolve correctly into TaskConstraints.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    profiles = load_profiles(_write_flat_profiles(tmp_path))
    objective = ParsedObjective(
        name="demo",
        description="Demo",
        tests_constraint_profile="default",
        target_files=["src/demo.py"],
    )
    resolved = resolve_constraints(objective, profiles, scope="tests")
    assert resolved.primary.max_cyclomatic_complexity == 10
    assert resolved.secondary.require_docstrings is True
    assert resolved.guidance == ["keep it simple"]
