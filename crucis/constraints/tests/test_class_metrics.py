"""Tests for Layer 1 class-level metric constraints."""

from crucis.constraints.checker import check_constraints
from crucis.models import ConstraintSet, TaskConstraints

_SMALL_CLASS = """\
class Foo:
    def __init__(self):
        self.x = 1

    def bar(self):
        return self.x
"""

_MANY_METHODS_CLASS = """\
class Bloated:
    def m1(self): pass
    def m2(self): pass
    def m3(self): pass
    def m4(self): pass
    def m5(self): pass
    def m6(self): pass
"""

_MANY_FIELDS_CLASS = """\
class Big:
    def __init__(self):
        self.a = 1
        self.b = 2
        self.c = 3
        self.d = 4
        self.e = 5
        self.f = 6
"""

_ANNOTATED_FIELDS_CLASS = """\
class Config:
    host: str
    port: int
    debug: bool
    timeout: float
    def __init__(self):
        self.host = "localhost"
        self.port = 8080
        self.debug = False
        self.timeout = 30.0
"""

_LONG_CLASS = (
    "class LongClass:\n"
    + "".join(f"    x{i} = {i}\n" for i in range(50))
)

_COMPLEX_METHODS_CLASS = """\
class Complex:
    def decide(self, x):
        if x > 0:
            if x > 10:
                if x > 100:
                    return "big"
                return "medium"
            return "small"
        return "negative"

    def simple(self):
        return 1
"""

_NO_CLASS = """\
def standalone():
    return 42
"""


def _make_constraints(**kwargs):
    """Build a TaskConstraints with given primary constraints.

    Returns:
        TaskConstraints with the specified primary constraints.
    """
    return TaskConstraints(
        primary=ConstraintSet(**kwargs),
        secondary=ConstraintSet(),
        target_files=[],
    )


class TestMethodsPerClass:
    """Tests for max_methods_per_class constraint."""

    def test_under_limit_passes(self):
        """Verify class with few methods passes."""
        c = _make_constraints(max_methods_per_class=5)
        primary, _ = check_constraints(_SMALL_CLASS, c)
        assert primary.passed

    def test_over_limit_fails(self):
        """Verify class with too many methods fails."""
        c = _make_constraints(max_methods_per_class=3)
        primary, _ = check_constraints(_MANY_METHODS_CLASS, c)
        assert not primary.passed
        assert any("Bloated" in v and "methods" in v for v in primary.violations)

    def test_at_limit_passes(self):
        """Verify class at exact limit passes."""
        c = _make_constraints(max_methods_per_class=6)
        primary, _ = check_constraints(_MANY_METHODS_CLASS, c)
        assert primary.passed

    def test_no_class_passes(self):
        """Verify code without classes passes."""
        c = _make_constraints(max_methods_per_class=1)
        primary, _ = check_constraints(_NO_CLASS, c)
        assert primary.passed

    def test_metric_recorded(self):
        """Verify method count metric is recorded."""
        c = _make_constraints(max_methods_per_class=100)
        primary, _ = check_constraints(_MANY_METHODS_CLASS, c)
        assert primary.metrics["methods_per_class"] == 6


class TestFieldsPerClass:
    """Tests for max_fields_per_class constraint."""

    def test_under_limit_passes(self):
        """Verify class with few fields passes."""
        c = _make_constraints(max_fields_per_class=5)
        primary, _ = check_constraints(_SMALL_CLASS, c)
        assert primary.passed

    def test_over_limit_fails(self):
        """Verify class with too many fields fails."""
        c = _make_constraints(max_fields_per_class=3)
        primary, _ = check_constraints(_MANY_FIELDS_CLASS, c)
        assert not primary.passed
        assert any("Big" in v and "fields" in v for v in primary.violations)

    def test_annotated_fields_counted(self):
        """Verify class-level annotated fields are counted."""
        c = _make_constraints(max_fields_per_class=3)
        primary, _ = check_constraints(_ANNOTATED_FIELDS_CLASS, c)
        assert not primary.passed

    def test_no_class_passes(self):
        """Verify code without classes passes."""
        c = _make_constraints(max_fields_per_class=1)
        primary, _ = check_constraints(_NO_CLASS, c)
        assert primary.passed


class TestClassLines:
    """Tests for max_class_lines constraint."""

    def test_under_limit_passes(self):
        """Verify small class passes."""
        c = _make_constraints(max_class_lines=20)
        primary, _ = check_constraints(_SMALL_CLASS, c)
        assert primary.passed

    def test_over_limit_fails(self):
        """Verify long class fails."""
        c = _make_constraints(max_class_lines=10)
        primary, _ = check_constraints(_LONG_CLASS, c)
        assert not primary.passed
        assert any("LongClass" in v and "lines" in v for v in primary.violations)

    def test_no_class_passes(self):
        """Verify code without classes passes."""
        c = _make_constraints(max_class_lines=1)
        primary, _ = check_constraints(_NO_CLASS, c)
        assert primary.passed


class TestWeightedMethodsPerClass:
    """Tests for max_weighted_methods_per_class constraint."""

    def test_simple_class_passes(self):
        """Verify class with low-complexity methods passes."""
        c = _make_constraints(max_weighted_methods_per_class=20)
        primary, _ = check_constraints(_SMALL_CLASS, c)
        assert primary.passed

    def test_complex_class_fails(self):
        """Verify class with high total complexity fails."""
        c = _make_constraints(max_weighted_methods_per_class=2)
        primary, _ = check_constraints(_COMPLEX_METHODS_CLASS, c)
        assert not primary.passed
        assert any("WMC" in v for v in primary.violations)

    def test_no_class_passes(self):
        """Verify code without classes passes."""
        c = _make_constraints(max_weighted_methods_per_class=1)
        primary, _ = check_constraints(_NO_CLASS, c)
        assert primary.passed

    def test_metric_recorded(self):
        """Verify WMC metric is recorded."""
        c = _make_constraints(max_weighted_methods_per_class=100)
        primary, _ = check_constraints(_COMPLEX_METHODS_CLASS, c)
        assert primary.metrics["weighted_methods_per_class"] > 0
