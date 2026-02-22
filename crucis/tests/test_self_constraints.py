from pathlib import Path

import pytest
import yaml

from crucis.constraints.checker import check_constraints
from crucis.models import ConstraintSet, TaskConstraints


@pytest.fixture(scope="module")
def orchestrator_constraints():
    """Load orchestrator constraints from YAML for self-testing.

    Returns:
        TaskConstraints loaded from constraints/crucis.yaml.
    """
    constraints_path = Path(__file__).parent.parent.parent / "constraints" / "crucis.yaml"
    with open(constraints_path) as f:
        data = yaml.safe_load(f)
    return TaskConstraints(
        primary=ConstraintSet(**data.get("primary", {})),
        secondary=ConstraintSet(**data.get("secondary", {})),
        target_files=data.get("target_files", []),
    )


@pytest.fixture(scope="module")
def project_root():
    """Provide the project root directory path.

    Returns:
        Path to the project root.
    """
    return Path(__file__).parent.parent.parent


def _get_repo_python_files() -> list[str]:
    """Return all tracked Python files in the repository.

    Returns:
        Sorted repo-relative Python file paths.
    """
    project_root = Path(__file__).parent.parent.parent
    excluded_roots = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".benchmarks",
        ".claude",
        ".idea",
        "site",
    }
    paths: list[str] = []
    for file_path in project_root.rglob("*.py"):
        rel = file_path.relative_to(project_root)
        if any(part in excluded_roots for part in rel.parts):
            continue
        paths.append(str(rel))
    return sorted(paths)


def _get_primary_target_files() -> list[str]:
    """Read primary target files from constraints YAML.

    Returns:
        List of repo-relative target file paths for primary checks.
    """
    constraints_path = Path(__file__).parent.parent.parent / "constraints" / "crucis.yaml"
    with open(constraints_path) as f:
        data = yaml.safe_load(f)
    return data.get("target_files", [])


class TestSelfConstraints:
    """Tests that repository Python files meet self-constraints."""

    @pytest.mark.parametrize("target_file", _get_primary_target_files())
    def test_repository_meets_primary_constraints(
        self, target_file, orchestrator_constraints, project_root
    ):
        """Test that the target file meets primary constraints.

        Args:
            target_file: Path to the source file being checked.
            orchestrator_constraints: Loaded TaskConstraints.
            project_root: Path to the project root.
        """
        source_path = project_root / target_file
        if not source_path.exists():
            pytest.skip(f"{target_file} not yet implemented")
        source_code = source_path.read_text()
        primary_result, _ = check_constraints(source_code, orchestrator_constraints)
        assert (
            primary_result.passed
        ), f"{target_file} violates primary constraints: {primary_result.violations}"

    @pytest.mark.parametrize("target_file", _get_repo_python_files())
    def test_repository_meets_secondary_constraints(
        self, target_file, orchestrator_constraints, project_root
    ):
        """Test that the target file meets secondary constraints.

        Args:
            target_file: Path to the source file being checked.
            orchestrator_constraints: Loaded TaskConstraints.
            project_root: Path to the project root.
        """
        source_path = project_root / target_file
        if not source_path.exists():
            pytest.skip(f"{target_file} not yet implemented")
        source_code = source_path.read_text()
        _, secondary_result = check_constraints(source_code, orchestrator_constraints)
        assert (
            secondary_result.passed
        ), f"{target_file} violates secondary constraints: {secondary_result.violations}"
