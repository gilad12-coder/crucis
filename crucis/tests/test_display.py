"""Tests for display helpers."""

from io import StringIO

from rich.console import Console

from crucis.display import (
    display_adversarial_report,
    display_checkpoint_table,
    display_error,
    display_evaluation_attempt,
    display_evaluation_result,
    display_fit_complete,
    display_hardening_cycle,
    display_sandbox_status,
    display_task_header,
    display_test_suite_source,
)
from crucis.models import AdversarialReport, CheckpointState, TaskProgress, TrainingStatus
from crucis.persistence.policy import OptimizerStatus


def _capture_console() -> tuple[Console, StringIO]:
    """capture console.

    Returns:
        Tuple containing grouped return values.
    """
    buf = StringIO()
    return Console(file=buf, force_terminal=False, color_system=None), buf


def test_display_test_suite_source_renders_title():
    """Test suite panel should render expected title text."""
    console, buf = _capture_console()
    display_test_suite_source("def test_x():\n    assert True", console=console)
    assert "Generated Test Suite" in buf.getvalue()


def test_display_adversarial_report_shows_sections():
    """Adversarial report should render key section labels."""
    console, buf = _capture_console()
    report = AdversarialReport(
        attack_vectors=["hardcode returns"],
        generalization_gaps=["no edge case"],
        suggested_probe_tests=["randomized inputs"],
        correctness_issues=[],
    )
    display_adversarial_report(report, console=console)
    output = buf.getvalue()
    assert "Attack vectors" in output
    assert "Generalization gaps" in output


def test_display_checkpoint_table_lists_task_names():
    """Checkpoint table should contain task names and statuses."""
    console, buf = _capture_console()
    state = CheckpointState(
        task_progress=[
            TaskProgress(name="add", status=TrainingStatus.complete),
            TaskProgress(name="sub", status=TrainingStatus.pending),
        ]
    )
    display_checkpoint_table(state, console=console)
    output = buf.getvalue()
    assert "add" in output
    assert "sub" in output


def test_display_task_header_contains_processing():
    """Task header should indicate processing context."""
    console, buf = _capture_console()
    display_task_header("merge", console=console)
    assert "Training Task" in buf.getvalue()


def test_display_fit_complete_counts_completed_tasks():
    """Fit completion summary should display completed/total count."""
    console, buf = _capture_console()
    state = CheckpointState(
        task_progress=[
            TaskProgress(name="a", status=TrainingStatus.complete),
            TaskProgress(name="b", status=TrainingStatus.pending),
        ]
    )
    display_fit_complete(state, console=console)
    assert "1/2" in buf.getvalue()


def test_display_error_prints_error_prefix():
    """Error output should include the error prefix."""
    console, buf = _capture_console()
    display_error("bad input", console=console)
    assert "Error:" in buf.getvalue()


def test_display_evaluation_attempt_and_result():
    """Evaluation attempt/result helpers should print expected text."""
    console, buf = _capture_console()
    display_evaluation_attempt(2, 5, console=console)
    display_evaluation_result(False, console=console)
    output = buf.getvalue()
    assert "2/5" in output
    assert "Evaluation failed" in output


def test_display_sandbox_status_messages():
    """Sandbox availability message should match boolean input."""
    console, buf = _capture_console()
    display_sandbox_status(False, console=console)
    assert "unavailable" in buf.getvalue().lower()


def test_display_hardening_cycle_shows_cycle_and_task():
    """Hardening cycle display should render cycle number and task name."""
    console, buf = _capture_console()
    display_hardening_cycle("shunting_yard", 2, 3, console=console)
    output = buf.getvalue()
    assert "2/3" in output
    assert "shunting_yard" in output


def test_display_checkpoint_table_includes_optimizer_status_when_present():
    """Checkpoint view should print background optimizer status details."""
    console, buf = _capture_console()
    state = CheckpointState(task_progress=[TaskProgress(name="add")])
    status = OptimizerStatus(
        state="completed",
        promoted=True,
        message="candidate promoted",
    )
    display_checkpoint_table(state, optimizer_status=status, console=console)
    output = buf.getvalue().lower()
    assert "background optimizer" in output
    assert "candidate promoted" in output


def test_display_checkpoint_table_shows_candidate_ready_hint():
    """Checkpoint view should include promote hint when candidate is ready."""
    console, buf = _capture_console()
    state = CheckpointState(task_progress=[TaskProgress(name="add")])
    status = OptimizerStatus(
        state="completed",
        candidate_ready=True,
        candidate_run_id="run-42",
    )
    display_checkpoint_table(state, optimizer_status=status, console=console)
    output = buf.getvalue()
    assert "candidate ready" in output.lower()
    assert "crucis promote --run-id run-42" in output
