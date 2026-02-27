"""Tests for pure helper functions in crucis.core.generation."""

from types import SimpleNamespace

from crucis.core.generation import _has_actionable_gaps, _validate_generation_attempt
from crucis.models import ConstraintSet, TaskConstraints


def _make_constraints() -> TaskConstraints:
    """Build minimal TaskConstraints for validation tests.

    Returns:
        TaskConstraints with permissive primary limits.
    """
    return TaskConstraints(
        primary=ConstraintSet(max_cyclomatic_complexity=10, max_total_lines=200),
        secondary=ConstraintSet(),
        target_files=["src/solution.py"],
    )


# _has_actionable_gaps


class TestHasActionableGaps:
    """Tests for _has_actionable_gaps adversarial report triage."""

    def test_empty_report_returns_false(self):
        """A report with no actionable fields should return False."""
        report = SimpleNamespace(
            correctness_issues=[],
            probe_succeeded=False,
            generalization_gaps=[],
            suggested_probe_tests=[],
        )
        assert _has_actionable_gaps(report) is False

    def test_correctness_issues_returns_true(self):
        """A report with correctness issues should be actionable."""
        report = SimpleNamespace(
            correctness_issues=["wrong expected value"],
            probe_succeeded=False,
            generalization_gaps=[],
            suggested_probe_tests=[],
        )
        assert _has_actionable_gaps(report) is True

    def test_probe_succeeded_returns_true(self):
        """A report where the cheating probe passed should be actionable."""
        report = SimpleNamespace(
            correctness_issues=[],
            probe_succeeded=True,
            generalization_gaps=[],
            suggested_probe_tests=[],
        )
        assert _has_actionable_gaps(report) is True

    def test_generalization_gaps_returns_true(self):
        """A report with generalization gaps should be actionable."""
        report = SimpleNamespace(
            correctness_issues=[],
            probe_succeeded=False,
            generalization_gaps=["missing edge case"],
            suggested_probe_tests=[],
        )
        assert _has_actionable_gaps(report) is True

    def test_suggested_probes_returns_true(self):
        """A report with suggested probe tests should be actionable."""
        report = SimpleNamespace(
            correctness_issues=[],
            probe_succeeded=False,
            generalization_gaps=[],
            suggested_probe_tests=["test negative inputs"],
        )
        assert _has_actionable_gaps(report) is True

    def test_missing_attributes_returns_false(self):
        """A report object missing all relevant attributes should return False."""
        report = SimpleNamespace()
        assert _has_actionable_gaps(report) is False


# _validate_generation_attempt


class TestValidateGenerationAttempt:
    """Tests for _validate_generation_attempt syntax and constraint checks."""

    def test_empty_source_fails(self):
        """Empty train suite source should fail syntax validation."""
        passed, feedback, count = _validate_generation_attempt(
            train_suite_source="",
            constraints=_make_constraints(),
            n=1,
            max_attempts=3,
            logger=None,
            task_name="add",
            prev_violation_count=0,
            constraint_feedback="",
        )
        assert passed is False

    def test_syntax_error_fails(self):
        """Source with a syntax error should fail validation."""
        bad_source = "def test_add(\n    assert True\n"
        passed, feedback, count = _validate_generation_attempt(
            train_suite_source=bad_source,
            constraints=_make_constraints(),
            n=1,
            max_attempts=3,
            logger=None,
            task_name="add",
            prev_violation_count=0,
            constraint_feedback="",
        )
        assert passed is False

    def test_valid_source_passes(self):
        """Syntactically valid source meeting constraints should pass."""
        valid_source = (
            '"""Test suite for add."""\n'
            "\n"
            "import pytest\n"
            "\n"
            "\n"
            "def test_add_positive():\n"
            '    """Test addition of positive numbers."""\n'
            "    assert 1 + 2 == 3\n"
        )
        passed, feedback, count = _validate_generation_attempt(
            train_suite_source=valid_source,
            constraints=_make_constraints(),
            n=1,
            max_attempts=3,
            logger=None,
            task_name="add",
            prev_violation_count=0,
            constraint_feedback="",
        )
        assert passed is True
        assert feedback == ""
        assert count == 0
