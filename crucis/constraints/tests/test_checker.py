from crucis.constraints.checker import check_constraints
from crucis.models import ConstraintResult, ConstraintSet, TaskConstraints

# --- Sample code for testing ---

SIMPLE_FUNCTION = '''\
def add(a, b):
    """Add two numbers.

    Args:
        a: First number.
        b: Second number.

    Returns:
        Sum of a and b.
    """
    return a + b
'''

SUMMARY_ONLY_DOCSTRING = '''\
def add(a, b):
    """Add two numbers."""
    return a + b
'''

BRANCHING_FUNCTION = """\
def classify(x):
    if x > 100:
        return "very high"
    elif x > 50:
        return "high"
    elif x > 25:
        return "medium"
    elif x > 10:
        return "low"
    elif x > 0:
        return "very low"
    else:
        return "non-positive"
"""

NO_DOCSTRING_FUNCTION = """\
def add(a, b):
    return a + b
"""

FORBIDDEN_IMPORT_CODE = '''\
import os
import subprocess

def run_command(cmd):
    """Run a shell command."""
    return subprocess.run(cmd, shell=True)
'''

LONG_FUNCTION = "def long_func():\n" + "    x = 1\n" * 100

MULTI_FUNCTION_CODE = (
    '''\
def short_func():
    """Short and sweet."""
    return 1

def long_func():
    """This one is too long."""
'''
    + "    x = 1\n" * 100
)

O1_FUNCTION = """\
def constant(x):
    return x + 1
"""

ON_FUNCTION = """\
def linear(items):
    for item in items:
        print(item)
"""

ON2_FUNCTION = """\
def quadratic(items):
    for i in items:
        for j in items:
            print(i, j)
"""

ON3_FUNCTION = """\
def cubic(items):
    for i in items:
        for j in items:
            for k in items:
                print(i, j, k)
"""

SORT_IN_LOOP = """\
def find_sorted(items):
    for group in items:
        group.sort()
"""

SORTED_IN_LOOP = """\
def find_sorted(items):
    for group in items:
        s = sorted(group)
"""

INDEX_IN_LOOP = """\
def find_index(items, targets):
    for t in targets:
        items.index(t)
"""

IN_LIST_IN_LOOP = """\
def has_item(items, targets):
    for t in targets:
        if t in items:
            pass
"""

LIST_COMPREHENSION = """\
def make_list(items):
    return [x * 2 for x in items]
"""

NESTED_COMPREHENSION = """\
def make_grid(rows, cols):
    return [[r * c for c in cols] for r in rows]
"""

RECURSIVE_FUNCTION = """\
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)
"""

SUM_IN_LOOP = """\
def total_sums(groups):
    for g in groups:
        sum(g)
"""

SORT_OUTSIDE_LOOP = """\
def sort_once(items):
    items.sort()
"""

APPEND_IN_LOOP = """\
def collect(items):
    result = []
    for x in items:
        result.append(x)
    return result
"""

APPEND_IN_NESTED_LOOPS = """\
def collect_nested(grid):
    result = []
    for row in grid:
        for cell in row:
            result.append(cell)
    return result
"""

LIST_MATERIALIZATION = """\
def to_list(items):
    return list(items)
"""

SLICE_COPY = """\
def halve(items):
    return items[:len(items) // 2]
"""

COPY_CALL = """\
def clone(items):
    return items.copy()
"""

GENERATOR_EXPRESSION = """\
def lazy_sum(items):
    return sum(x * 2 for x in items)
"""

SPACE_O1 = """\
def add(a, b):
    return a + b
"""

MANY_PARAMS_FUNCTION = """\
def many(a, b, c, d, e, f):
    return a + b + c + d + e + f
"""

FEW_PARAMS_FUNCTION = """\
def few(a, b):
    return a + b
"""

DEEPLY_NESTED = """\
def deep(x):
    if x > 0:
        for i in range(x):
            if i > 5:
                while True:
                    break
"""

SHALLOW_NESTING = """\
def shallow(x):
    if x > 0:
        return x
    return 0
"""

PRINT_FUNCTION = """\
def greet(name):
    print(f"Hello {name}")
    return name
"""

NO_PRINT_FUNCTION = """\
def greet(name):
    return f"Hello {name}"
"""

STAR_IMPORT_CODE = """\
from os.path import *

def get_home():
    return expanduser("~")
"""

NORMAL_IMPORT_CODE = """\
from os.path import expanduser

def get_home():
    return expanduser("~")
"""

MUTABLE_DEFAULT_CODE = """\
def append_to(item, target=[]):
    target.append(item)
    return target
"""

SAFE_DEFAULT_CODE = """\
def append_to(item, target=None):
    if target is None:
        target = []
    target.append(item)
    return target
"""

GLOBAL_STATE_CODE = """\
cache = {}
counter = 0

def increment():
    global counter
    counter += 1
"""

NO_GLOBAL_STATE_CODE = """\
CONSTANT = 42

def get_value():
    return CONSTANT
"""

MANY_RETURNS_FUNCTION = """\
def classify(x):
    if x > 100:
        return "very high"
    if x > 50:
        return "high"
    if x > 25:
        return "medium"
    if x > 10:
        return "low"
    return "very low"
"""

FEW_RETURNS_FUNCTION = """\
def sign(x):
    if x > 0:
        return 1
    return -1
"""

# --- Correctness fixtures ---

BARE_EXCEPT_CODE = """\
def process():
    try:
        do_something()
    except:
        pass
"""

SPECIFIC_EXCEPT_CODE = """\
def process():
    try:
        do_something()
    except ValueError:
        handle()
"""

TRY_EXCEPT_PASS_CODE = """\
def process():
    try:
        do_something()
    except Exception:
        pass
"""

TRY_EXCEPT_LOG_CODE = """\
def process():
    try:
        do_something()
    except Exception as e:
        log(e)
"""

RETURN_IN_FINALLY_CODE = """\
def process():
    try:
        return 1
    finally:
        return 2
"""

NO_RETURN_IN_FINALLY_CODE = """\
def process():
    try:
        return 1
    finally:
        cleanup()
"""

UNREACHABLE_CODE = """\
def process():
    return 1
    x = 2
"""

NO_UNREACHABLE_CODE = """\
def process():
    if True:
        return 1
    return 2
"""

DUPLICATE_DICT_KEYS_CODE = """\
def process():
    return {'a': 1, 'b': 2, 'a': 3}
"""

NO_DUPLICATE_DICT_KEYS_CODE = """\
def process():
    return {'a': 1, 'b': 2, 'c': 3}
"""

LOOP_CLOSURE_CODE = """\
def process():
    funcs = []
    for i in range(10):
        funcs.append(lambda: i)
    return funcs
"""

NO_LOOP_CLOSURE_CODE = """\
def process():
    funcs = []
    for i in range(10):
        funcs.append(lambda i=i: i)
    return funcs
"""

CALL_DEFAULT_CODE = """\
import datetime
def process(ts=datetime.datetime.now()):
    return ts
"""

NO_CALL_DEFAULT_CODE = """\
def process(ts=None):
    return ts
"""

SHADOW_BUILTIN_CODE = """\
def process():
    list = [1, 2, 3]
    return list
"""

NO_SHADOW_BUILTIN_CODE = """\
def process():
    items = [1, 2, 3]
    return items
"""

OPEN_WITHOUT_WITH_CODE = """\
def process():
    f = open("file.txt")
    data = f.read()
    f.close()
    return data
"""

OPEN_WITH_WITH_CODE = """\
def process():
    with open("file.txt") as f:
        return f.read()
"""

# --- Security fixtures ---

EVAL_CODE = """\
def process(expr):
    return eval(expr)
"""

NO_EVAL_CODE = """\
def process(expr):
    return int(expr)
"""

EXEC_CODE = """\
def process(code):
    exec(code)
"""

NO_EXEC_CODE = """\
def process(code):
    return code
"""

PICKLE_CODE = """\
import pickle
def process(data):
    return pickle.loads(data)
"""

NO_PICKLE_CODE = """\
import json
def process(data):
    return json.loads(data)
"""

UNSAFE_YAML_CODE = """\
import yaml
def process(data):
    return yaml.load(data)
"""

SAFE_YAML_CODE = """\
import yaml
def process(data):
    return yaml.load(data, Loader=yaml.SafeLoader)
"""

SHELL_TRUE_CODE = """\
import subprocess
def process(cmd):
    return subprocess.run(cmd, shell=True)
"""

NO_SHELL_TRUE_CODE = """\
import subprocess
def process(cmd):
    return subprocess.run(cmd)
"""

HARDCODED_SECRET_CODE = """\
def connect():
    password = "super_secret_123"
    return password
"""

NO_HARDCODED_SECRET_CODE = """\
import os
def connect():
    password = os.environ.get("PASSWORD")
    return password
"""

NO_TIMEOUT_CODE = """\
import requests
def fetch(url):
    return requests.get(url)
"""

WITH_TIMEOUT_CODE = """\
import requests
def fetch(url):
    return requests.get(url, timeout=30)
"""

# --- Maintainability fixtures ---

HIGH_COGNITIVE_CODE = """\
def process(x, items):
    if x > 0:
        for item in items:
            if item > 0:
                if item > x:
                    return True
    return False
"""

LOW_COGNITIVE_CODE = """\
def process(x):
    if x > 0:
        return True
    return False
"""

MANY_LOCALS_CODE = """\
def process():
    a = 1
    b = 2
    c = 3
    d = 4
    e = 5
    f = 6
    return a + b + c + d + e + f
"""

FEW_LOCALS_CODE = """\
def process():
    x = 1
    return x
"""

DEBUGGER_CODE = """\
import pdb
def process():
    pdb.set_trace()
    return 1
"""

NO_DEBUGGER_CODE = """\
def process():
    return 1
"""

NESTED_IMPORT_CODE = """\
def process():
    import os
    return os.getcwd()
"""

NO_NESTED_IMPORT_CODE = """\
import os
def process():
    return os.getcwd()
"""

NO_ANNOTATIONS_CODE = """\
def add(a, b):
    return a + b
"""

WITH_ANNOTATIONS_CODE = """\
def add(a: int, b: int) -> int:
    return a + b
"""


# --- Individual metric tests ---


class TestCheckConstraintsMetrics:
    """Tests for individual constraint metric checks."""

    def test_check_constraints_simple_function_passes_complexity(self):
        """Test that a simple function passes complexity constraints."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_cyclomatic_complexity=5),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(SIMPLE_FUNCTION, constraints)
        assert primary_result.passed is True
        assert "cyclomatic_complexity" in primary_result.metrics
        assert primary_result.metrics["cyclomatic_complexity"] <= 2

    def test_check_constraints_branching_function_fails_complexity(self):
        """Test that a branching function fails complexity constraints."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_cyclomatic_complexity=3),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(BRANCHING_FUNCTION, constraints)
        assert primary_result.passed is False
        assert "cyclomatic_complexity" in primary_result.metrics
        assert primary_result.metrics["cyclomatic_complexity"] >= 5

    def test_check_constraints_long_function_fails_line_count(self):
        """Test that a long function fails line count constraints."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_lines_per_function=10),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(LONG_FUNCTION, constraints)
        assert primary_result.passed is False
        assert any("lines" in v.lower() for v in primary_result.violations)

    def test_check_constraints_docstring_present_passes(self):
        """Test that functions with docstrings pass the docstring check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(),
            secondary=ConstraintSet(require_docstrings=True),
            target_files=[],
        )
        _, secondary_result = check_constraints(SIMPLE_FUNCTION, constraints)
        assert secondary_result.passed is True

        _, secondary_result = check_constraints(NO_DOCSTRING_FUNCTION, constraints)
        assert secondary_result.passed is False
        assert any("docstring" in v.lower() for v in secondary_result.violations)

    def test_check_constraints_summary_only_docstring_fails(self):
        """Test that a summary-only docstring fails when Args/Returns are expected."""
        constraints = TaskConstraints(
            primary=ConstraintSet(),
            secondary=ConstraintSet(require_docstrings=True),
            target_files=[],
        )
        _, secondary_result = check_constraints(SUMMARY_ONLY_DOCSTRING, constraints)
        assert secondary_result.passed is False
        assert any(
            "args" in v.lower() or "returns" in v.lower() for v in secondary_result.violations
        )

    def test_check_constraints_forbidden_import_fails(self):
        """Test that forbidden imports cause a constraint failure."""
        constraints = TaskConstraints(
            primary=ConstraintSet(allowed_imports=["os"]),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(FORBIDDEN_IMPORT_CODE, constraints)
        assert primary_result.passed is False
        assert any("subprocess" in v.lower() for v in primary_result.violations)

    def test_check_constraints_multi_function_one_exceeds_lines(self):
        """Test that one function exceeding line limit fails the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_lines_per_function=10),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(MULTI_FUNCTION_CODE, constraints)
        assert primary_result.passed is False

    def test_check_constraints_o1_passes_on(self):
        """Test that O(1) function passes O(n) time complexity constraint."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_time_complexity="O(n)"),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(O1_FUNCTION, constraints)
        assert primary_result.passed is True
        assert primary_result.metrics["time_complexity"] == "O(1)"

    def test_check_constraints_on_passes_on(self):
        """Test that O(n) function passes O(n) time complexity constraint."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_time_complexity="O(n)"),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(ON_FUNCTION, constraints)
        assert primary_result.passed is True
        assert primary_result.metrics["time_complexity"] == "O(n)"

    def test_check_constraints_on2_fails_on(self):
        """Test that O(n^2) function fails O(n) time complexity constraint."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_time_complexity="O(n)"),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(ON2_FUNCTION, constraints)
        assert primary_result.passed is False
        assert primary_result.metrics["time_complexity"] == "O(n^2)"
        assert any("time complexity" in v.lower() for v in primary_result.violations)

    def test_check_constraints_on2_passes_on2(self):
        """Test that O(n^2) function passes O(n^2) time complexity constraint."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_time_complexity="O(n^2)"),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(ON2_FUNCTION, constraints)
        assert primary_result.passed is True

    def test_check_constraints_on3_fails_on2(self):
        """Test that O(n^3) function fails O(n^2) time complexity constraint."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_time_complexity="O(n^2)"),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(ON3_FUNCTION, constraints)
        assert primary_result.passed is False
        assert primary_result.metrics["time_complexity"] == "O(n^3)"

    def test_check_constraints_max_parameters_passes(self):
        """Test that a function with few parameters passes the limit."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_parameters=3),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(FEW_PARAMS_FUNCTION, constraints)
        assert primary_result.passed is True
        assert primary_result.metrics["max_parameters"] == 2

    def test_check_constraints_max_parameters_fails(self):
        """Test that a function with too many parameters fails the limit."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_parameters=3),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(MANY_PARAMS_FUNCTION, constraints)
        assert primary_result.passed is False
        assert primary_result.metrics["max_parameters"] == 6
        assert any("parameter" in v.lower() for v in primary_result.violations)

    def test_check_constraints_max_nested_depth_passes(self):
        """Test that shallow nesting passes the depth constraint."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_nested_depth=2),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(SHALLOW_NESTING, constraints)
        assert primary_result.passed is True

    def test_check_constraints_max_nested_depth_fails(self):
        """Test that deep nesting fails the depth constraint."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_nested_depth=2),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(DEEPLY_NESTED, constraints)
        assert primary_result.passed is False
        assert any(
            "nesting" in v.lower() or "depth" in v.lower() for v in primary_result.violations
        )

    def test_check_constraints_no_print_passes(self):
        """Test that code without print statements passes the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_print_statements=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(NO_PRINT_FUNCTION, constraints)
        assert primary_result.passed is True

    def test_check_constraints_no_print_fails(self):
        """Test that code with print statements fails the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_print_statements=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(PRINT_FUNCTION, constraints)
        assert primary_result.passed is False
        assert any("print" in v.lower() for v in primary_result.violations)

    def test_check_constraints_no_star_imports_passes(self):
        """Test that code without star imports passes the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_star_imports=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(NORMAL_IMPORT_CODE, constraints)
        assert primary_result.passed is True

    def test_check_constraints_no_star_imports_fails(self):
        """Test that code with star imports fails the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_star_imports=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(STAR_IMPORT_CODE, constraints)
        assert primary_result.passed is False
        assert any(
            "star" in v.lower() or "wildcard" in v.lower() or "*" in v
            for v in primary_result.violations
        )

    def test_check_constraints_no_mutable_defaults_passes(self):
        """Test that code without mutable defaults passes the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_mutable_defaults=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(SAFE_DEFAULT_CODE, constraints)
        assert primary_result.passed is True

    def test_check_constraints_no_mutable_defaults_fails(self):
        """Test that code with mutable defaults fails the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_mutable_defaults=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(MUTABLE_DEFAULT_CODE, constraints)
        assert primary_result.passed is False
        assert any(
            "mutable" in v.lower() or "default" in v.lower() for v in primary_result.violations
        )

    def test_check_constraints_no_global_state_passes(self):
        """Test that code without global state passes the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_global_state=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(NO_GLOBAL_STATE_CODE, constraints)
        assert primary_result.passed is True

    def test_check_constraints_no_global_state_fails(self):
        """Test that code with global state fails the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_global_state=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(GLOBAL_STATE_CODE, constraints)
        assert primary_result.passed is False
        assert any("global" in v.lower() for v in primary_result.violations)

    def test_check_constraints_max_return_statements_passes(self):
        """Test that a function with few returns passes the limit."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_return_statements=3),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(FEW_RETURNS_FUNCTION, constraints)
        assert primary_result.passed is True
        assert primary_result.metrics["max_return_statements"] == 2

    def test_check_constraints_max_return_statements_fails(self):
        """Test that a function with many returns fails the limit."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_return_statements=3),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(MANY_RETURNS_FUNCTION, constraints)
        assert primary_result.passed is False
        assert primary_result.metrics["max_return_statements"] == 5
        assert any("return" in v.lower() for v in primary_result.violations)

    # --- Correctness constraints ---

    def test_no_bare_except_passes(self):
        """Test that specific except clauses pass the bare except check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_bare_except=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(SPECIFIC_EXCEPT_CODE, constraints)
        assert result.passed is True

    def test_no_bare_except_fails(self):
        """Test that bare except clauses fail the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_bare_except=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(BARE_EXCEPT_CODE, constraints)
        assert result.passed is False
        assert any("bare except" in v.lower() for v in result.violations)

    def test_no_try_except_pass_passes(self):
        """Test that except with logging passes the silenced exception check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_try_except_pass=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(TRY_EXCEPT_LOG_CODE, constraints)
        assert result.passed is True

    def test_no_try_except_pass_fails(self):
        """Test that except with pass fails the silenced exception check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_try_except_pass=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(TRY_EXCEPT_PASS_CODE, constraints)
        assert result.passed is False
        assert any("silenced" in v.lower() or "pass" in v.lower() for v in result.violations)

    def test_no_return_in_finally_passes(self):
        """Test that finally without return passes the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_return_in_finally=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(NO_RETURN_IN_FINALLY_CODE, constraints)
        assert result.passed is True

    def test_no_return_in_finally_fails(self):
        """Test that return in finally block fails the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_return_in_finally=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(RETURN_IN_FINALLY_CODE, constraints)
        assert result.passed is False
        assert any("finally" in v.lower() for v in result.violations)

    def test_no_unreachable_code_passes(self):
        """Test that reachable code passes the unreachable code check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_unreachable_code=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(NO_UNREACHABLE_CODE, constraints)
        assert result.passed is True

    def test_no_unreachable_code_fails(self):
        """Test that unreachable code after return fails the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_unreachable_code=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(UNREACHABLE_CODE, constraints)
        assert result.passed is False
        assert any("unreachable" in v.lower() for v in result.violations)

    def test_no_duplicate_dict_keys_passes(self):
        """Test that unique dict keys pass the duplicate key check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_duplicate_dict_keys=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(NO_DUPLICATE_DICT_KEYS_CODE, constraints)
        assert result.passed is True

    def test_no_duplicate_dict_keys_fails(self):
        """Test that duplicate dict keys fail the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_duplicate_dict_keys=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(DUPLICATE_DICT_KEYS_CODE, constraints)
        assert result.passed is False
        assert any("duplicate" in v.lower() for v in result.violations)

    def test_no_loop_variable_closure_passes(self):
        """Test that properly captured loop variables pass the closure check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_loop_variable_closure=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(NO_LOOP_CLOSURE_CODE, constraints)
        assert result.passed is True

    def test_no_loop_variable_closure_fails(self):
        """Test that uncaptured loop variable closures fail the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_loop_variable_closure=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(LOOP_CLOSURE_CODE, constraints)
        assert result.passed is False
        assert any(
            "loop variable" in v.lower() or "closure" in v.lower() for v in result.violations
        )

    def test_no_mutable_call_defaults_passes(self):
        """Test that non-call defaults pass the mutable call default check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_mutable_call_in_defaults=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(NO_CALL_DEFAULT_CODE, constraints)
        assert result.passed is True

    def test_no_mutable_call_defaults_fails(self):
        """Test that function call defaults fail the mutable call default check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_mutable_call_in_defaults=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(CALL_DEFAULT_CODE, constraints)
        assert result.passed is False
        assert any("call" in v.lower() or "default" in v.lower() for v in result.violations)

    def test_no_shadowing_builtins_passes(self):
        """Test that non-builtin variable names pass the shadowing check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_shadowing_builtins=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(NO_SHADOW_BUILTIN_CODE, constraints)
        assert result.passed is True

    def test_no_shadowing_builtins_fails(self):
        """Test that shadowing builtin names fails the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_shadowing_builtins=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(SHADOW_BUILTIN_CODE, constraints)
        assert result.passed is False
        assert any("list" in v.lower() for v in result.violations)

    def test_no_open_without_with_passes(self):
        """Test that open() inside a with statement passes the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_open_without_context_manager=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(OPEN_WITH_WITH_CODE, constraints)
        assert result.passed is True

    def test_no_open_without_with_fails(self):
        """Test that open() without a context manager fails the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_open_without_context_manager=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(OPEN_WITHOUT_WITH_CODE, constraints)
        assert result.passed is False
        assert any("open" in v.lower() for v in result.violations)

    # --- Security constraints ---

    def test_no_eval_passes(self):
        """Test that code without eval passes the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_eval=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(NO_EVAL_CODE, constraints)
        assert result.passed is True

    def test_no_eval_fails(self):
        """Test that code using eval fails the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_eval=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(EVAL_CODE, constraints)
        assert result.passed is False
        assert any("eval" in v.lower() for v in result.violations)

    def test_no_exec_passes(self):
        """Test that code without exec passes the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_exec=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(NO_EXEC_CODE, constraints)
        assert result.passed is True

    def test_no_exec_fails(self):
        """Test that code using exec fails the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_exec=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(EXEC_CODE, constraints)
        assert result.passed is False
        assert any("exec" in v.lower() for v in result.violations)

    def test_no_unsafe_deserialization_passes(self):
        """Test that safe deserialization passes the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_unsafe_deserialization=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(NO_PICKLE_CODE, constraints)
        assert result.passed is True

    def test_no_unsafe_deserialization_fails(self):
        """Test that pickle usage fails the unsafe deserialization check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_unsafe_deserialization=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(PICKLE_CODE, constraints)
        assert result.passed is False
        assert any("deserialization" in v.lower() for v in result.violations)

    def test_no_unsafe_yaml_passes(self):
        """Test that safe YAML loading passes the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_unsafe_yaml=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(SAFE_YAML_CODE, constraints)
        assert result.passed is True

    def test_no_unsafe_yaml_fails(self):
        """Test that unsafe YAML loading fails the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_unsafe_yaml=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(UNSAFE_YAML_CODE, constraints)
        assert result.passed is False
        assert any("yaml" in v.lower() for v in result.violations)

    def test_no_shell_true_passes(self):
        """Test that subprocess without shell=True passes the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_shell_true=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(NO_SHELL_TRUE_CODE, constraints)
        assert result.passed is True

    def test_no_shell_true_fails(self):
        """Test that subprocess with shell=True fails the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_shell_true=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(SHELL_TRUE_CODE, constraints)
        assert result.passed is False
        assert any("shell" in v.lower() for v in result.violations)

    def test_no_hardcoded_secrets_passes(self):
        """Test that code without hardcoded secrets passes the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_hardcoded_secrets=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(NO_HARDCODED_SECRET_CODE, constraints)
        assert result.passed is True

    def test_no_hardcoded_secrets_fails(self):
        """Test that code with hardcoded secrets fails the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_hardcoded_secrets=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(HARDCODED_SECRET_CODE, constraints)
        assert result.passed is False
        assert any("secret" in v.lower() or "password" in v.lower() for v in result.violations)

    def test_no_requests_without_timeout_passes(self):
        """Test that requests with timeout passes the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_requests_without_timeout=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(WITH_TIMEOUT_CODE, constraints)
        assert result.passed is True

    def test_no_requests_without_timeout_fails(self):
        """Test that requests without timeout fails the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_requests_without_timeout=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(NO_TIMEOUT_CODE, constraints)
        assert result.passed is False
        assert any("timeout" in v.lower() for v in result.violations)

    # --- Maintainability constraints ---

    def test_max_cognitive_complexity_passes(self):
        """Test that low cognitive complexity passes the limit."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_cognitive_complexity=10),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(LOW_COGNITIVE_CODE, constraints)
        assert result.passed is True
        assert result.metrics["cognitive_complexity"] <= 3

    def test_max_cognitive_complexity_fails(self):
        """Test that high cognitive complexity fails the limit."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_cognitive_complexity=3),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(HIGH_COGNITIVE_CODE, constraints)
        assert result.passed is False
        assert any("cognitive" in v.lower() for v in result.violations)

    def test_max_local_variables_passes(self):
        """Test that few local variables pass the limit."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_local_variables=3),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(FEW_LOCALS_CODE, constraints)
        assert result.passed is True
        assert result.metrics["max_local_variables"] == 1

    def test_max_local_variables_fails(self):
        """Test that many local variables fail the limit."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_local_variables=3),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(MANY_LOCALS_CODE, constraints)
        assert result.passed is False
        assert result.metrics["max_local_variables"] == 6

    def test_no_debugger_statements_passes(self):
        """Test that code without debugger statements passes the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_debugger_statements=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(NO_DEBUGGER_CODE, constraints)
        assert result.passed is True

    def test_no_debugger_statements_fails(self):
        """Test that code with debugger statements fails the check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_debugger_statements=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(DEBUGGER_CODE, constraints)
        assert result.passed is False
        assert any("debugger" in v.lower() for v in result.violations)

    def test_no_nested_imports_passes(self):
        """Test that top-level imports pass the nested import check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_nested_imports=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(NO_NESTED_IMPORT_CODE, constraints)
        assert result.passed is True

    def test_no_nested_imports_fails(self):
        """Test that imports inside functions fail the nested import check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(no_nested_imports=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(NESTED_IMPORT_CODE, constraints)
        assert result.passed is False
        assert any("nested import" in v.lower() for v in result.violations)

    def test_require_type_annotations_passes(self):
        """Test that annotated functions pass the type annotation check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(require_type_annotations=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(WITH_ANNOTATIONS_CODE, constraints)
        assert result.passed is True

    def test_require_type_annotations_fails(self):
        """Test that unannotated functions fail the type annotation check."""
        constraints = TaskConstraints(
            primary=ConstraintSet(require_type_annotations=True),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(NO_ANNOTATIONS_CODE, constraints)
        assert result.passed is False
        assert any("annotation" in v.lower() for v in result.violations)


# --- Two-gate evaluation tests ---


class TestCheckConstraintsTwoGate:
    """Tests for two-gate constraint evaluation."""

    def test_check_constraints_primary_passes(self):
        """Test that primary constraints pass for simple code."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_cyclomatic_complexity=10),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(SIMPLE_FUNCTION, constraints)
        assert primary_result.passed is True

    def test_check_constraints_primary_fails(self):
        """Test that primary constraints fail for complex code."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_cyclomatic_complexity=2),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, _ = check_constraints(BRANCHING_FUNCTION, constraints)
        assert primary_result.passed is False
        assert len(primary_result.violations) > 0

    def test_check_constraints_secondary_passes(self):
        """Test that secondary constraints pass for documented code."""
        constraints = TaskConstraints(
            primary=ConstraintSet(),
            secondary=ConstraintSet(require_docstrings=True),
            target_files=[],
        )
        _, secondary_result = check_constraints(SIMPLE_FUNCTION, constraints)
        assert secondary_result.passed is True

    def test_check_constraints_secondary_fails(self):
        """Test that secondary constraints fail for undocumented code."""
        constraints = TaskConstraints(
            primary=ConstraintSet(),
            secondary=ConstraintSet(require_docstrings=True),
            target_files=[],
        )
        _, secondary_result = check_constraints(NO_DOCSTRING_FUNCTION, constraints)
        assert secondary_result.passed is False

    def test_check_constraints_returns_both_results(self):
        """Test that check_constraints returns both primary and secondary results."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_cyclomatic_complexity=10),
            secondary=ConstraintSet(require_docstrings=True),
            target_files=[],
        )
        result = check_constraints(SIMPLE_FUNCTION, constraints)
        assert isinstance(result, tuple)
        assert len(result) == 2
        primary_result, secondary_result = result
        assert isinstance(primary_result, ConstraintResult)
        assert isinstance(secondary_result, ConstraintResult)

    def test_check_constraints_skips_none_fields(self):
        """Test that check_constraints skips None constraint fields."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_cyclomatic_complexity=10),
            secondary=ConstraintSet(),
            target_files=[],
        )
        primary_result, secondary_result = check_constraints(SIMPLE_FUNCTION, constraints)
        assert primary_result.passed is True
        assert secondary_result.passed is True


# --- Enhanced time complexity tests ---


class TestEnhancedTimeComplexity:
    """Tests for enhanced time complexity detection."""

    def _time(self, src: str) -> str:
        """Helper to extract time complexity metric."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_time_complexity="O(n^3)"),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(src, constraints)
        return result.metrics["time_complexity"]

    def test_sort_in_loop_is_on2(self):
        """Test that .sort() inside a loop is detected as O(n^2)."""
        assert self._time(SORT_IN_LOOP) == "O(n^2)"

    def test_sorted_in_loop_is_on2(self):
        """Test that sorted() inside a loop is detected as O(n^2)."""
        assert self._time(SORTED_IN_LOOP) == "O(n^2)"

    def test_index_in_loop_is_on2(self):
        """Test that .index() inside a loop is detected as O(n^2)."""
        assert self._time(INDEX_IN_LOOP) == "O(n^2)"

    def test_in_list_in_loop_is_on2(self):
        """Test that 'x in list' inside a loop is detected as O(n^2)."""
        assert self._time(IN_LIST_IN_LOOP) == "O(n^2)"

    def test_list_comprehension_is_on(self):
        """Test that a list comprehension is O(n)."""
        assert self._time(LIST_COMPREHENSION) == "O(n)"

    def test_nested_comprehension_is_on2(self):
        """Test that a nested comprehension is O(n^2)."""
        assert self._time(NESTED_COMPREHENSION) == "O(n^2)"

    def test_recursive_function_is_on(self):
        """Test that a directly recursive function is at least O(n)."""
        assert self._time(RECURSIVE_FUNCTION) == "O(n)"

    def test_sum_in_loop_is_on2(self):
        """Test that sum() inside a loop is detected as O(n^2)."""
        assert self._time(SUM_IN_LOOP) == "O(n^2)"

    def test_sort_outside_loop_is_on(self):
        """Test that .sort() outside a loop is O(n), not O(n^2)."""
        assert self._time(SORT_OUTSIDE_LOOP) == "O(1)"

    def test_existing_o1_unchanged(self):
        """Test that O(1) function still detected correctly."""
        assert self._time(O1_FUNCTION) == "O(1)"

    def test_existing_on_unchanged(self):
        """Test that O(n) function still detected correctly."""
        assert self._time(ON_FUNCTION) == "O(n)"

    def test_existing_on2_unchanged(self):
        """Test that O(n^2) nested loop still detected correctly."""
        assert self._time(ON2_FUNCTION) == "O(n^2)"

    def test_existing_on3_unchanged(self):
        """Test that O(n^3) triple nested loop still detected correctly."""
        assert self._time(ON3_FUNCTION) == "O(n^3)"

    def test_sort_in_loop_fails_on_constraint(self):
        """Test that .sort() in loop fails an O(n) constraint."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_time_complexity="O(n)"),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(SORT_IN_LOOP, constraints)
        assert result.passed is False


# --- Space complexity tests ---


class TestSpaceComplexity:
    """Tests for space complexity detection."""

    def _space(self, src: str) -> str:
        """Helper to extract space complexity metric."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_space_complexity="O(n^3)"),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(src, constraints)
        return result.metrics["space_complexity"]

    def test_no_allocation_is_o1(self):
        """Test that a function with no allocations is O(1)."""
        assert self._space(SPACE_O1) == "O(1)"

    def test_list_comprehension_is_on(self):
        """Test that a list comprehension allocates O(n)."""
        assert self._space(LIST_COMPREHENSION) == "O(n)"

    def test_append_in_loop_is_on(self):
        """Test that .append() in a loop is O(n)."""
        assert self._space(APPEND_IN_LOOP) == "O(n)"

    def test_append_in_nested_loops_is_on2(self):
        """Test that .append() in nested loops is O(n^2)."""
        assert self._space(APPEND_IN_NESTED_LOOPS) == "O(n^2)"

    def test_nested_comprehension_is_on2(self):
        """Test that nested comprehension is O(n^2)."""
        assert self._space(NESTED_COMPREHENSION) == "O(n^2)"

    def test_list_materialization_is_on(self):
        """Test that list(iterable) is O(n)."""
        assert self._space(LIST_MATERIALIZATION) == "O(n)"

    def test_slice_is_on(self):
        """Test that a slice creates O(n) space."""
        assert self._space(SLICE_COPY) == "O(n)"

    def test_copy_is_on(self):
        """Test that .copy() creates O(n) space."""
        assert self._space(COPY_CALL) == "O(n)"

    def test_generator_expression_is_o1(self):
        """Test that generator expression is O(1) (lazy)."""
        assert self._space(GENERATOR_EXPRESSION) == "O(1)"

    def test_space_fails_constraint(self):
        """Test that O(n) space fails an O(1) constraint."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_space_complexity="O(1)"),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(LIST_COMPREHENSION, constraints)
        assert result.passed is False
        assert any("space complexity" in v.lower() for v in result.violations)

    def test_space_passes_constraint(self):
        """Test that O(1) space passes an O(n) constraint."""
        constraints = TaskConstraints(
            primary=ConstraintSet(max_space_complexity="O(n)"),
            secondary=ConstraintSet(),
            target_files=[],
        )
        result, _ = check_constraints(SPACE_O1, constraints)
        assert result.passed is True
