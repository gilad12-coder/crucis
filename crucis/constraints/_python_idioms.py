"""Python-specific idiom checkers for Layer 2 convention constraints."""

import ast
import re

from crucis.models import ConstraintSet

_SNAKE_CASE = re.compile(r"^_*[a-z][a-z0-9_]*$")
_CAP_WORDS = re.compile(r"^_*[A-Z][a-zA-Z0-9]*$")
_UPPER_CASE = re.compile(r"^_*[A-Z][A-Z0-9_]*$")
_DUNDER = re.compile(r"^__[a-z][a-z0-9_]*__$")


def _chk_naming_conventions(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    if cs.enforce_naming_conventions is not True:
        return
    violations = _find_naming_violations(src)
    m["naming_violations"] = len(violations)
    for name, kind, expected, lineno in violations:
        v.append(
            f"'{name}' (line {lineno}) should be {expected} ({kind})"
        )


def _chk_single_char_names(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    if cs.no_single_char_names is not True:
        return
    bad_names = _find_single_char_names(src)
    m["single_char_names"] = len(bad_names)
    for name, lineno in bad_names:
        v.append(f"Single-character variable '{name}' at line {lineno} — use a descriptive name")


def _chk_unnecessary_else_after_return(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    if cs.no_unnecessary_else_after_return is not True:
        return
    locations = _find_unnecessary_else(src)
    m["unnecessary_else_count"] = len(locations)
    for lineno in locations:
        v.append(f"Unnecessary 'else' after return/raise at line {lineno} — remove the else block")


def _chk_len_as_condition(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    if cs.no_len_as_condition is not True:
        return
    locations = _find_len_as_condition(src)
    m["len_as_condition_count"] = len(locations)
    for lineno in locations:
        v.append(
            f"Use truthiness instead of len() comparison at line {lineno}"
            " — e.g. 'if items:' instead of 'if len(items) > 0:'"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_naming_violations(src: str) -> list[tuple[str, str, str, int]]:
    """Return (name, kind, expected_style, lineno) for naming violations."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    violations: list[tuple[str, str, str, int]] = []
    for node in ast.iter_child_nodes(tree):
        # Functions at module level
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not _DUNDER.match(node.name) and not _SNAKE_CASE.match(node.name):
                violations.append((node.name, "function", "snake_case", node.lineno))
        # Classes at module level
        elif isinstance(node, ast.ClassDef):
            if not _CAP_WORDS.match(node.name):
                violations.append((node.name, "class", "CapWords", node.lineno))
            _check_class_methods(node, violations)
    return violations


def _check_class_methods(
    cls: ast.ClassDef,
    violations: list[tuple[str, str, str, int]],
) -> None:
    """Check method names inside a class definition."""
    for child in cls.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not _DUNDER.match(child.name) and not _SNAKE_CASE.match(child.name):
                violations.append(
                    (child.name, "method", "snake_case", child.lineno)
                )


def _find_single_char_names(src: str) -> list[tuple[str, int]]:
    """Return (name, lineno) for single-char variable assignments."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    # Collect exempt positions: loop vars, comprehension vars, lambda/function params
    exempt: set[tuple[str, int]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            exempt.add((node.target.id, node.target.lineno))
        elif isinstance(node, ast.For) and isinstance(node.target, ast.Tuple):
            for elt in node.target.elts:
                if isinstance(elt, ast.Name):
                    exempt.add((elt.id, elt.lineno))
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            for gen in node.generators:
                if isinstance(gen.target, ast.Name):
                    exempt.add((gen.target.id, gen.target.lineno))
                elif isinstance(gen.target, ast.Tuple):
                    for elt in gen.target.elts:
                        if isinstance(elt, ast.Name):
                            exempt.add((elt.id, elt.lineno))
    bad: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and len(node.id) == 1
            and node.id != "_"
            and (node.id, node.lineno) not in exempt
        ):
            bad.append((node.id, node.lineno))
    return bad


def _is_terminal(stmts: list[ast.stmt]) -> bool:
    """Check if a statement list ends with a terminal statement."""
    if not stmts:
        return False
    last = stmts[-1]
    return isinstance(last, (ast.Return, ast.Raise, ast.Continue, ast.Break))


def _find_unnecessary_else(src: str) -> list[int]:
    """Return line numbers of unnecessary else blocks after return/raise."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    # Collect If nodes that are part of an elif chain (appear as sole orelse child)
    elif_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            elif_nodes.add(id(node.orelse[0]))
    locations: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if not node.orelse:
            continue
        # Skip elif chains — orelse is a single If node
        if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            continue
        # Skip if this If is itself an elif (part of a chain)
        if id(node) in elif_nodes:
            continue
        if _is_terminal(node.body):
            locations.append(node.orelse[0].lineno)
    return locations


def _is_len_call(node: ast.expr) -> bool:
    """Check if node is a call to len()."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "len"
    )


def _is_zero(node: ast.expr) -> bool:
    """Check if node is the literal 0."""
    return isinstance(node, ast.Constant) and node.value == 0


def _find_len_as_condition(src: str) -> list[int]:
    """Return line numbers of len() compared to 0 in conditions."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    locations: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.While)):
            if _test_is_len_comparison(node.test):
                locations.append(node.lineno)
    return locations


def _test_is_len_comparison(test: ast.expr) -> bool:
    """Check if a condition expression is len(x) compared to 0."""
    if not isinstance(test, ast.Compare):
        return False
    # len(x) > 0, len(x) == 0, len(x) != 0, len(x) >= 1, etc.
    if _is_len_call(test.left):
        for comparator in test.comparators:
            if _is_zero(comparator):
                return True
    # 0 < len(x), 0 == len(x), etc.
    if _is_zero(test.left):
        for comparator in test.comparators:
            if _is_len_call(comparator):
                return True
    return False
