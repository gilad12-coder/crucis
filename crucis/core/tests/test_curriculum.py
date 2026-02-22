"""Tests for curriculum generation."""

from crucis.core.curriculum import build_curriculum, write_curriculum_to_workspace
from crucis.models import (
    AdversarialReport,
    CheckpointState,
    ConstraintSet,
    ParsedObjective,
    TaskConstraints,
    TaskObjective,
    TaskProgress,
    TrainingStatus,
)


def _objective() -> ParsedObjective:
    """objective.

    Returns:
        Result of `_objective`.
    """
    return ParsedObjective(
        name="calculator",
        description="A simple calculator",
        target_files=["src/calc.py"],
        tasks=[
            TaskObjective(
                name="add",
                signature="add(a: int, b: int) -> int",
                description="Add numbers",
                train_evals=[{"input": "(1, 2)", "output": "3"}],
                holdout_evals=[{"input": "(10, 20)", "output": "30"}],
            )
        ],
    )


def _state() -> CheckpointState:
    """state.

    Returns:
        Result of `_state`.
    """
    return CheckpointState(
        task_progress=[
            TaskProgress(
                name="add",
                status=TrainingStatus.complete,
                train_suite_source="def test_add():\n    assert add(1, 2) == 3",
                adversarial_report=AdversarialReport(
                    attack_vectors=["hardcode output"],
                    generalization_gaps=["no negative numbers"],
                    suggested_probe_tests=["test randomized values"],
                ),
            )
        ]
    )


def _constraints_map() -> dict[str, TaskConstraints]:
    """constraints map.

    Returns:
        Computed text result for this operation.
    """
    return {
        "add": TaskConstraints(
            primary=ConstraintSet(max_lines_per_function=25),
            secondary=ConstraintSet(require_docstrings=True),
            target_files=["src/calc.py"],
            guidance=["Prefer pure functions"],
        )
    }


def test_build_curriculum_contains_core_sections():
    """Curriculum should include objective, tasks, constraints, and adversarial findings."""
    curriculum = build_curriculum(_state(), _objective(), _constraints_map())
    assert "Evaluation Curriculum" in curriculum
    assert "Objective: calculator" in curriculum
    assert "### add" in curriculum
    assert "attack vectors" in curriculum.lower()
    assert "primary constraints" in curriculum.lower()


def test_build_curriculum_excludes_holdout_literals():
    """Holdout values should not appear in visible curriculum output."""
    curriculum = build_curriculum(_state(), _objective(), _constraints_map())
    assert "(10, 20)" not in curriculum
    assert "30" not in curriculum


def test_build_curriculum_shows_implementation_constraints():
    """Curriculum should include implementation constraints when provided."""
    impl_map = {
        "add": TaskConstraints(
            primary=ConstraintSet(max_cyclomatic_complexity=8),
            secondary=ConstraintSet(no_eval=True),
            target_files=["src/calc.py"],
            guidance=["Keep functions small"],
        )
    }
    curriculum = build_curriculum(_state(), _objective(), _constraints_map(), impl_map)
    assert "implementation constraints" in curriculum.lower()
    assert "max cyclomatic complexity" in curriculum.lower()


def test_build_curriculum_omits_implementation_section_when_none():
    """Curriculum should not include implementation section when map is None."""
    curriculum = build_curriculum(_state(), _objective(), _constraints_map(), None)
    assert "implementation constraints" not in curriculum.lower()


def test_build_curriculum_labels_test_constraints():
    """Existing constraints section should be labeled as test constraints."""
    curriculum = build_curriculum(_state(), _objective(), _constraints_map())
    assert "test constraints" in curriculum.lower()


def test_write_curriculum_to_workspace(tmp_path):
    """Curriculum writer should emit curriculum.md file in workspace.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    path = write_curriculum_to_workspace("# x", tmp_path)
    assert path.name == "curriculum.md"
    assert path.read_text(encoding="utf-8") == "# x"
