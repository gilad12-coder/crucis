"""Tests for custom constraint check plugin system."""

import pytest

from crucis.constraints.checker import check_constraints
from crucis.constraints.plugins import (
    clear_custom_checks,
    get_registered_checks,
    register_custom_check,
    run_custom_checks,
    unregister_custom_check,
)
from crucis.models import ConstraintSet, TaskConstraints


@pytest.fixture(autouse=True)
def _clean_registry():
    """Clear plugin registry before and after each test."""
    clear_custom_checks()
    yield
    clear_custom_checks()


# Registry management


class TestPluginRegistry:
    """Tests for plugin registration and discovery."""

    def test_register_and_retrieve(self):
        """Registered check appears in the registry.

        Args:
            (no args — uses autouse fixture)
        """

        def my_check(src, config, v, m):
            pass

        register_custom_check("my_check", my_check)
        assert "my_check" in get_registered_checks()

    def test_duplicate_registration_raises(self):
        """Registering the same name twice raises ValueError."""

        def my_check(src, config, v, m):
            pass

        register_custom_check("dup", my_check)
        with pytest.raises(ValueError, match="already registered"):
            register_custom_check("dup", my_check)

    def test_unregister_removes_check(self):
        """Unregistered check is no longer in registry."""

        def my_check(src, config, v, m):
            pass

        register_custom_check("temp", my_check)
        unregister_custom_check("temp")
        assert "temp" not in get_registered_checks()

    def test_unregister_nonexistent_is_noop(self):
        """Unregistering a non-existent check does not raise."""
        unregister_custom_check("nonexistent")

    def test_clear_empties_registry(self):
        """clear_custom_checks removes all entries."""

        def a(src, config, v, m):
            pass

        def b(src, config, v, m):
            pass

        register_custom_check("a", a)
        register_custom_check("b", b)
        clear_custom_checks()
        assert len(get_registered_checks()) == 0


# run_custom_checks execution


class TestRunCustomChecks:
    """Tests for run_custom_checks execution."""

    def test_calls_registered_checker_with_config(self):
        """Registered checker receives config value and can append violations."""

        def check_foo(src, config, v, m):
            if config is True:
                v.append("foo violation")
                m["foo"] = True

        register_custom_check("check_foo", check_foo)
        violations: list[str] = []
        metrics: dict = {}
        run_custom_checks("x = 1", {"check_foo": True}, violations, metrics)
        assert violations == ["foo violation"]
        assert metrics["foo"] is True

    def test_skips_unregistered_check_names(self):
        """Config keys without registered checkers are silently skipped."""
        violations: list[str] = []
        metrics: dict = {}
        run_custom_checks("x = 1", {"unknown_check": True}, violations, metrics)
        assert violations == []

    def test_checker_receives_arbitrary_config_value(self):
        """Config value can be any type (int, str, dict, etc.)."""
        received: dict = {}

        def check_limit(src, config, v, m):
            received["config"] = config

        register_custom_check("check_limit", check_limit)
        run_custom_checks("x = 1", {"check_limit": 42}, [], {})
        assert received["config"] == 42


# Integration with check_constraints two-gate flow


class TestCheckConstraintsWithPlugins:
    """Tests for plugin integration with the two-gate evaluation flow."""

    def test_custom_check_in_primary_gate(self):
        """Custom check violation in primary gate causes primary failure."""

        def always_fail(src, config, v, m):
            if config:
                v.append("custom primary fail")

        register_custom_check("always_fail", always_fail)
        constraints = TaskConstraints(
            primary=ConstraintSet(),
            secondary=ConstraintSet(),
            target_files=[],
        )
        custom = {"primary": {"always_fail": True}}
        primary, secondary = check_constraints("x = 1\n", constraints, custom_checks=custom)
        assert primary.passed is False
        assert "custom primary fail" in primary.violations

    def test_custom_check_in_secondary_gate(self):
        """Custom check violation in secondary gate causes secondary failure."""

        def always_fail(src, config, v, m):
            if config:
                v.append("custom secondary fail")

        register_custom_check("always_fail", always_fail)
        constraints = TaskConstraints(
            primary=ConstraintSet(),
            secondary=ConstraintSet(),
            target_files=[],
        )
        custom = {"secondary": {"always_fail": True}}
        primary, secondary = check_constraints("x = 1\n", constraints, custom_checks=custom)
        assert primary.passed is True
        assert secondary.passed is False
        assert "custom secondary fail" in secondary.violations

    def test_secondary_skipped_when_primary_fails(self):
        """Custom checks in secondary gate are skipped when primary fails."""
        call_log: list[str] = []

        def logging_check(src, config, v, m):
            call_log.append("called")
            v.append("fail")

        register_custom_check("logging_check", logging_check)
        constraints = TaskConstraints(
            primary=ConstraintSet(),
            secondary=ConstraintSet(),
            target_files=[],
        )
        custom = {"primary": {"logging_check": True}, "secondary": {"logging_check": True}}
        primary, _secondary = check_constraints("x = 1\n", constraints, custom_checks=custom)
        assert primary.passed is False
        assert len(call_log) == 1

    def test_no_custom_checks_is_backward_compatible(self):
        """Omitting custom_checks produces identical behaviour."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_cyclomatic_complexity=10),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result_without = check_constraints("def f(): return 1\n", constraints)
        result_with = check_constraints("def f(): return 1\n", constraints, custom_checks=None)
        assert result_without[0].passed == result_with[0].passed
        assert result_without[0].violations == result_with[0].violations

    def test_custom_check_metrics_merge_with_builtin(self):
        """Custom check metrics appear alongside built-in metrics."""

        def add_metric(src, config, v, m):
            m["custom_metric"] = 42

        register_custom_check("add_metric", add_metric)
        constraints = TaskConstraints(
            primary=ConstraintSet(max_cyclomatic_complexity=10),
            secondary=ConstraintSet(),
            target_files=[],
        )
        custom = {"primary": {"add_metric": True}}
        primary, _ = check_constraints("def f(): return 1\n", constraints, custom_checks=custom)
        assert primary.passed is True
        assert primary.metrics["custom_metric"] == 42
        assert "cyclomatic_complexity" in primary.metrics
