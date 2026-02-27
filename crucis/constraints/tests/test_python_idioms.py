"""Tests for Layer 2 Python-specific idiom constraints."""

from crucis.constraints.checker import check_constraints
from crucis.models import ConstraintSet, TaskConstraints


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


# ---------------------------------------------------------------------------
# Naming conventions
# ---------------------------------------------------------------------------

_GOOD_NAMES = """\
class MyClass:
    def my_method(self):
        pass

def my_function():
    pass
"""

_BAD_FUNCTION_NAME = """\
def MyFunction():
    pass
"""

_BAD_CLASS_NAME = """\
class my_class:
    pass
"""

_BAD_METHOD_NAME = """\
class Foo:
    def BadMethod(self):
        pass
"""

_DUNDER_METHOD = """\
class Foo:
    def __init__(self):
        pass

    def __repr__(self):
        return "Foo"
"""

_PRIVATE_NAMES = """\
def _private_helper():
    pass

class _InternalClass:
    pass
"""


class TestNamingConventions:
    """Tests for enforce_naming_conventions constraint."""

    def test_good_names_pass(self):
        """Verify snake_case functions and CapWords classes pass."""
        c = _make_constraints(enforce_naming_conventions=True)
        primary, _ = check_constraints(_GOOD_NAMES, c)
        assert primary.passed

    def test_bad_function_name_fails(self):
        """Verify CamelCase function name is flagged."""
        c = _make_constraints(enforce_naming_conventions=True)
        primary, _ = check_constraints(_BAD_FUNCTION_NAME, c)
        assert not primary.passed
        assert any("MyFunction" in v and "snake_case" in v for v in primary.violations)

    def test_bad_class_name_fails(self):
        """Verify snake_case class name is flagged."""
        c = _make_constraints(enforce_naming_conventions=True)
        primary, _ = check_constraints(_BAD_CLASS_NAME, c)
        assert not primary.passed
        assert any("my_class" in v and "CapWords" in v for v in primary.violations)

    def test_bad_method_name_fails(self):
        """Verify CamelCase method name is flagged."""
        c = _make_constraints(enforce_naming_conventions=True)
        primary, _ = check_constraints(_BAD_METHOD_NAME, c)
        assert not primary.passed
        assert any("BadMethod" in v and "snake_case" in v for v in primary.violations)

    def test_dunder_methods_exempt(self):
        """Verify dunder methods are not flagged."""
        c = _make_constraints(enforce_naming_conventions=True)
        primary, _ = check_constraints(_DUNDER_METHOD, c)
        assert primary.passed

    def test_private_names_pass(self):
        """Verify leading-underscore names are accepted."""
        c = _make_constraints(enforce_naming_conventions=True)
        primary, _ = check_constraints(_PRIVATE_NAMES, c)
        assert primary.passed

    def test_disabled_by_default(self):
        """Verify constraint is inactive when not set."""
        c = _make_constraints()
        primary, _ = check_constraints(_BAD_FUNCTION_NAME, c)
        assert primary.passed


# ---------------------------------------------------------------------------
# Single-char names
# ---------------------------------------------------------------------------

_SINGLE_CHAR_ASSIGN = """\
def func():
    x = 5
    return x
"""

_LOOP_VAR_EXEMPT = """\
def func():
    for i in range(10):
        pass
"""

_COMPREHENSION_VAR_EXEMPT = """\
def func():
    result = [x for x in range(10)]
    return result
"""

_UNDERSCORE_EXEMPT = """\
def func():
    _ = some_call()
"""


class TestSingleCharNames:
    """Tests for no_single_char_names constraint."""

    def test_single_char_assignment_fails(self):
        """Verify single-char variable assignment is flagged."""
        c = _make_constraints(no_single_char_names=True)
        primary, _ = check_constraints(_SINGLE_CHAR_ASSIGN, c)
        assert not primary.passed
        assert any("'x'" in v for v in primary.violations)

    def test_loop_var_exempt(self):
        """Verify for-loop variables are exempt."""
        c = _make_constraints(no_single_char_names=True)
        primary, _ = check_constraints(_LOOP_VAR_EXEMPT, c)
        assert primary.passed

    def test_comprehension_var_exempt(self):
        """Verify list comprehension variables are exempt."""
        c = _make_constraints(no_single_char_names=True)
        primary, _ = check_constraints(_COMPREHENSION_VAR_EXEMPT, c)
        assert primary.passed

    def test_underscore_exempt(self):
        """Verify underscore throwaway variable is exempt."""
        c = _make_constraints(no_single_char_names=True)
        primary, _ = check_constraints(_UNDERSCORE_EXEMPT, c)
        assert primary.passed

    def test_disabled_by_default(self):
        """Verify constraint is inactive when not set."""
        c = _make_constraints()
        primary, _ = check_constraints(_SINGLE_CHAR_ASSIGN, c)
        assert primary.passed


# ---------------------------------------------------------------------------
# Unnecessary else after return
# ---------------------------------------------------------------------------

_UNNECESSARY_ELSE = """\
def func(x):
    if x > 0:
        return True
    else:
        return False
"""

_ELIF_CHAIN = """\
def func(x):
    if x > 0:
        return "positive"
    elif x < 0:
        return "negative"
    else:
        return "zero"
"""

_NO_TERMINAL = """\
def func(x):
    if x > 0:
        y = 1
    else:
        y = 2
    return y
"""

_RAISE_THEN_ELSE = """\
def func(x):
    if x < 0:
        raise ValueError("negative")
    else:
        return x
"""


class TestUnnecessaryElse:
    """Tests for no_unnecessary_else_after_return constraint."""

    def test_else_after_return_fails(self):
        """Verify else after return is flagged."""
        c = _make_constraints(no_unnecessary_else_after_return=True)
        primary, _ = check_constraints(_UNNECESSARY_ELSE, c)
        assert not primary.passed
        assert any("else" in v.lower() for v in primary.violations)

    def test_elif_chain_passes(self):
        """Verify elif chains are not flagged."""
        c = _make_constraints(no_unnecessary_else_after_return=True)
        primary, _ = check_constraints(_ELIF_CHAIN, c)
        assert primary.passed

    def test_no_terminal_in_if_passes(self):
        """Verify non-terminal if body is not flagged."""
        c = _make_constraints(no_unnecessary_else_after_return=True)
        primary, _ = check_constraints(_NO_TERMINAL, c)
        assert primary.passed

    def test_raise_then_else_fails(self):
        """Verify else after raise is flagged."""
        c = _make_constraints(no_unnecessary_else_after_return=True)
        primary, _ = check_constraints(_RAISE_THEN_ELSE, c)
        assert not primary.passed

    def test_disabled_by_default(self):
        """Verify constraint is inactive when not set."""
        c = _make_constraints()
        primary, _ = check_constraints(_UNNECESSARY_ELSE, c)
        assert primary.passed


# ---------------------------------------------------------------------------
# len() as condition
# ---------------------------------------------------------------------------

_LEN_GT_ZERO = """\
def func(items):
    if len(items) > 0:
        return True
"""

_LEN_EQ_ZERO = """\
def func(items):
    if len(items) == 0:
        return True
"""

_LEN_NE_ZERO = """\
def func(items):
    if len(items) != 0:
        return True
"""

_ZERO_LT_LEN = """\
def func(items):
    if 0 < len(items):
        return True
"""

_LEN_TRUTHINESS = """\
def func(items):
    if len(items):
        return True
"""

_TRUTHINESS_CHECK = """\
def func(items):
    if items:
        return True
"""


class TestLenAsCondition:
    """Tests for no_len_as_condition constraint."""

    def test_len_gt_zero_fails(self):
        """Verify len(x) > 0 is flagged."""
        c = _make_constraints(no_len_as_condition=True)
        primary, _ = check_constraints(_LEN_GT_ZERO, c)
        assert not primary.passed

    def test_len_eq_zero_fails(self):
        """Verify len(x) == 0 is flagged."""
        c = _make_constraints(no_len_as_condition=True)
        primary, _ = check_constraints(_LEN_EQ_ZERO, c)
        assert not primary.passed

    def test_len_ne_zero_fails(self):
        """Verify len(x) != 0 is flagged."""
        c = _make_constraints(no_len_as_condition=True)
        primary, _ = check_constraints(_LEN_NE_ZERO, c)
        assert not primary.passed

    def test_zero_lt_len_fails(self):
        """Verify 0 < len(x) is flagged."""
        c = _make_constraints(no_len_as_condition=True)
        primary, _ = check_constraints(_ZERO_LT_LEN, c)
        assert not primary.passed

    def test_len_truthiness_passes(self):
        """Verify if len(items): without comparison passes."""
        c = _make_constraints(no_len_as_condition=True)
        primary, _ = check_constraints(_LEN_TRUTHINESS, c)
        assert primary.passed

    def test_plain_truthiness_passes(self):
        """Verify if items: passes."""
        c = _make_constraints(no_len_as_condition=True)
        primary, _ = check_constraints(_TRUTHINESS_CHECK, c)
        assert primary.passed

    def test_disabled_by_default(self):
        """Verify constraint is inactive when not set."""
        c = _make_constraints()
        primary, _ = check_constraints(_LEN_GT_ZERO, c)
        assert primary.passed
