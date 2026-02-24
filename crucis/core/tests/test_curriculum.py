"""Tests for curriculum generation."""

from crucis.core.curriculum import build_curriculum, read_context_files, write_curriculum_to_workspace
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
                    correctness_issues=[],
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
    """Curriculum should include objective, tasks, and adversarial findings."""
    curriculum = build_curriculum(_state(), _objective(), _constraints_map())
    assert "Implementation Brief" in curriculum
    assert "Objective: calculator" in curriculum
    assert "### add" in curriculum
    assert "attack vectors" in curriculum.lower()


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


def test_build_curriculum_omits_test_constraints():
    """Brief should not include test constraints — only implementation constraints matter."""
    curriculum = build_curriculum(_state(), _objective(), _constraints_map())
    assert "test constraints" not in curriculum.lower()


def test_write_curriculum_to_workspace(tmp_path):
    """Curriculum writer should emit curriculum.md file in workspace.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    path = write_curriculum_to_workspace("# x", tmp_path)
    assert path.name == "brief.md"
    assert path.read_text(encoding="utf-8") == "# x"


def test_read_context_files_returns_contents(tmp_path):
    """Reader should return file contents keyed by relative path.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    src = tmp_path / "src"
    src.mkdir()
    (src / "helpers.py").write_text("def helper(): pass\n", encoding="utf-8")

    result = read_context_files(tmp_path, ["src/helpers.py"])
    assert "src/helpers.py" in result
    assert "def helper()" in result["src/helpers.py"]


def test_read_context_files_skips_missing(tmp_path):
    """Reader should silently skip files that don't exist.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    result = read_context_files(tmp_path, ["nonexistent.py"])
    assert result == {}


def test_read_context_files_truncates_long_files(tmp_path):
    """Reader should truncate files exceeding max_lines.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    long_content = "\n".join(f"line {i}" for i in range(100))
    (tmp_path / "big.py").write_text(long_content, encoding="utf-8")

    result = read_context_files(tmp_path, ["big.py"], max_lines=10)
    lines = result["big.py"].splitlines()
    assert len(lines) == 11  # 10 content + 1 truncation marker
    assert "truncated" in lines[-1].lower()


def test_build_curriculum_includes_context_files(tmp_path):
    """Curriculum should include context file contents when workspace is provided.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    src = tmp_path / "src"
    src.mkdir()
    (src / "calc.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
    (src / "utils.py").write_text("CONSTANT = 42\n", encoding="utf-8")

    objective = ParsedObjective(
        name="calculator",
        description="A simple calculator",
        target_files=["src/calc.py"],
        context_files=["src/utils.py"],
        tasks=[
            TaskObjective(
                name="add",
                description="Add numbers",
                train_evals=[{"input": "(1, 2)", "output": "3"}],
            )
        ],
    )

    curriculum = build_curriculum(
        _state(), objective, _constraints_map(), workspace=tmp_path
    )
    assert "Code Context" in curriculum
    assert "CONSTANT = 42" in curriculum


def test_build_curriculum_omits_context_sections_when_empty():
    """Curriculum without context_files should not contain context sections."""
    curriculum = build_curriculum(_state(), _objective(), _constraints_map())
    assert "Code Context" not in curriculum
