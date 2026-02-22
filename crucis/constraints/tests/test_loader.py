"""Tests for profile loading and constraint resolution."""

from pathlib import Path

import yaml

from crucis.constraints.loader import load_profiles, resolve_constraints
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
