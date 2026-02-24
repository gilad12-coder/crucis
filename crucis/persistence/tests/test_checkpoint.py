"""Tests for checkpoint state helpers."""

import pytest

from crucis.models import (
    AdversarialReport,
    CheckpointState,
    ParsedObjective,
    TaskObjective,
    TaskProgress,
    TrainingStatus,
)
from crucis.persistence.checkpoint import create_checkpoint, load_checkpoint, save_checkpoint


def test_training_status_values():
    """TrainingStatus should expose strict new status values."""
    assert {s.value for s in TrainingStatus} == {
        "pending",
        "train_suite_generated",
        "train_suite_approved",
        "adversarially_reviewed",
        "complete",
    }


def test_create_checkpoint_for_multi_task_objective():
    """Checkpoint creation should initialize one pending progress per task."""
    objective = ParsedObjective(
        name="auth",
        description="Auth",
        tasks=[TaskObjective(name="login"), TaskObjective(name="logout")],
    )
    state = create_checkpoint(objective)
    assert [p.name for p in state.task_progress] == ["login", "logout"]
    assert all(p.status == TrainingStatus.pending for p in state.task_progress)


def test_create_checkpoint_for_single_task_objective():
    """Single-task objective should create one progress entry from objective name."""
    objective = ParsedObjective(name="add", description="Add")
    state = create_checkpoint(objective)
    assert len(state.task_progress) == 1
    assert state.task_progress[0].name == "add"


def test_save_and_load_checkpoint_round_trip(tmp_path):
    """Saving and loading checkpoint should preserve data.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    state = CheckpointState(
        task_progress=[
            TaskProgress(
                name="add",
                status=TrainingStatus.adversarially_reviewed,
                train_suite_source="def test_add(): assert add(1,2)==3",
                adversarial_report=AdversarialReport(
                    attack_vectors=["hardcode"],
                    generalization_gaps=["negative numbers"],
                    suggested_probe_tests=["test negatives"],
                    correctness_issues=[],
                ),
            )
        ]
    )
    path = tmp_path / "checkpoint.json"
    save_checkpoint(state, path)

    loaded = load_checkpoint(path)
    assert loaded is not None
    assert loaded.task_progress[0].name == "add"
    assert loaded.task_progress[0].status == TrainingStatus.adversarially_reviewed
    assert loaded.task_progress[0].adversarial_report is not None
    assert loaded.task_progress[0].adversarial_report.attack_vectors == ["hardcode"]


def test_load_checkpoint_missing_returns_none(tmp_path):
    """Loading absent checkpoint path should return None.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    assert load_checkpoint(tmp_path / "missing.json") is None


def test_load_checkpoint_corrupted_raises_valueerror(tmp_path):
    """Corrupted checkpoint JSON should raise ValueError, not ValidationError.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    bad = tmp_path / "bad.json"
    bad.write_text('{"invalid": "data"}', encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_checkpoint(bad)
    assert "Invalid checkpoint file" in str(exc.value)
