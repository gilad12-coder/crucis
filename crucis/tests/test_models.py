"""Tests for Crucis data models."""

import pytest
from pydantic import ValidationError

from crucis.models import (
    AdversarialReport,
    CheckpointState,
    CLIResult,
    ConstraintSet,
    HoldoutEval,
    ParsedObjective,
    TaskConstraints,
    TaskObjective,
    TaskProgress,
    TrainEval,
    TrainingStatus,
    VerificationGranularity,
    validate_holdout_eval_entries,
)


class TestConstraintSet:
    """Tests for constraint model validation."""

    def test_rejects_invalid_positive_bounds(self):
        """ConstraintSet should reject non-positive bounded fields."""
        with pytest.raises(ValidationError):
            ConstraintSet(max_lines_per_function=0)


class TestCLIResult:
    """Tests for CLIResult model."""

    def test_parsed_json_optional(self):
        """CLIResult should allow parsed_json to be None."""
        result = CLIResult(stdout="ok", stderr="", exit_code=0, parsed_json=None)
        assert result.parsed_json is None


class TestObjectiveModels:
    """Tests for objective/task models."""

    def test_task_objective_defaults(self):
        """TaskObjective optional fields should default cleanly."""
        task = TaskObjective(name="add")
        assert task.description == ""
        assert task.signature is None
        assert task.train_evals == []
        assert task.holdout_evals == []
        assert task.tests_constraint_profile is None
        assert task.implementation_constraint_profile is None
        assert task.target_files == []

    def test_parsed_objective_required_fields(self):
        """ParsedObjective should preserve required fields."""
        objective = ParsedObjective(
            name="add",
            description="Add two numbers",
            train_evals=[TrainEval(input="(1, 2)", output="3")],
        )
        assert objective.name == "add"
        assert objective.description == "Add two numbers"
        assert objective.tasks == []
        assert objective.verification_granularity == VerificationGranularity.task

    def test_parsed_objective_with_tasks(self):
        """ParsedObjective should store nested task objectives."""
        objective = ParsedObjective(
            name="math",
            description="Math tasks",
            tasks=[
                TaskObjective(
                    name="sub",
                    train_evals=[TrainEval(input="(2, 1)", output="1")],
                    holdout_evals=[HoldoutEval(input="(10, 3)", output="7")],
                )
            ],
        )
        assert len(objective.tasks) == 1
        assert objective.tasks[0].name == "sub"

    def test_rejects_invalid_verification_granularity(self):
        """ParsedObjective should reject unknown verification granularity values."""
        with pytest.raises(ValidationError):
            ParsedObjective(
                name="add",
                description="Add",
                verification_granularity="unknown",  # type: ignore[arg-type]
            )


class TestAdversarialReport:
    """Tests for adversarial report model."""

    def test_defaults(self):
        """Optional probe fields should default to None/False."""
        report = AdversarialReport(
            attack_vectors=["hardcoded outputs"],
            generalization_gaps=["no large inputs"],
            suggested_probe_tests=["randomized args"],
            correctness_issues=[],
        )
        assert report.probe_code is None
        assert report.probe_succeeded is False


class TestCheckpointModels:
    """Tests for checkpoint status/progress models."""

    def test_training_status_values(self):
        """TrainingStatus enum should expose strict rebrand values."""
        assert {s.value for s in TrainingStatus} == {
            "pending",
            "train_suite_generated",
            "train_suite_approved",
            "adversarially_reviewed",
            "complete",
        }

    def test_checkpoint_state_shape(self):
        """CheckpointState should hold a task progress list."""
        state = CheckpointState(task_progress=[TaskProgress(name="add")])
        assert len(state.task_progress) == 1
        assert state.task_progress[0].status == TrainingStatus.pending


class TestHoldoutValidation:
    """Tests for strict holdout eval validation helpers."""

    def test_rejects_raw(self):
        """Holdout eval entries must not use raw format."""
        with pytest.raises(ValueError):
            validate_holdout_eval_entries([{"raw": "foo"}], "holdout_evals")

    def test_rejects_missing_fields(self):
        """Holdout eval entries must include input and output."""
        with pytest.raises(ValueError):
            validate_holdout_eval_entries([{"input": "(1)"}], "holdout_evals")

    def test_rejects_invalid_input_expression(self):
        """Holdout input expression must parse as Python eval expression."""
        with pytest.raises(ValueError):
            validate_holdout_eval_entries(
                [{"input": "(1, 2", "output": "3"}],
                "holdout_evals",
            )

    def test_rejects_invalid_output_expression(self):
        """Holdout output expression must parse as Python eval expression."""
        with pytest.raises(ValueError):
            validate_holdout_eval_entries(
                [{"input": "(1, 2)", "output": "3 +"}],
                "holdout_evals",
            )


class TestTaskConstraints:
    """Tests for TaskConstraints structure."""

    def test_builds_with_primary_secondary(self):
        """TaskConstraints should preserve primary/secondary fields."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_lines_per_function=20),
            secondary=ConstraintSet(require_docstrings=True),
            target_files=["src/add.py"],
            guidance=["Prefer pure functions"],
        )
        assert constraints.primary.max_lines_per_function == 20
        assert constraints.secondary.require_docstrings is True
        assert constraints.target_files == ["src/add.py"]
