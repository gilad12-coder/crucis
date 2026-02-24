"""Static analysis constraint checking using radon and AST inspection."""

import ast
import builtins
from collections import Counter

from radon.complexity import cc_visit

from crucis.constraints.plugins import run_custom_checks
from crucis.models import ConstraintResult, ConstraintSet, TaskConstraints


def check_constraints(
    source_code: str,
    constraints: TaskConstraints,
    custom_checks: dict | None = None,
) -> tuple[ConstraintResult, ConstraintResult]:
    """Check source code against primary and secondary constraints.

    Args:
        source_code: Python source code to analyze.
        constraints: TaskConstraints with primary and secondary gates.
        custom_checks: Optional mapping with ``"primary"`` and/or ``"secondary"``
            keys containing check-name-to-config-value dicts for custom plugins.

    Returns:
        Tuple of (primary_result, secondary_result).
    """
    primary = _evaluate(source_code, constraints.primary)
    primary = _apply_plugins(source_code, primary, (custom_checks or {}).get("primary"))
    if not primary.passed:
        secondary = ConstraintResult(passed=True, violations=[], metrics={})
    else:
        secondary = _evaluate(source_code, constraints.secondary)
        secondary = _apply_plugins(source_code, secondary, (custom_checks or {}).get("secondary"))
    return primary, secondary


def _apply_plugins(
    source_code: str,
    result: ConstraintResult,
    plugin_config: dict | None,
) -> ConstraintResult:
    """Run custom plugin checks and merge into an existing result.

    Args:
        source_code: Python source code to analyse.
        result: Existing constraint result to extend.
        plugin_config: Mapping of check names to config values, or None.

    Returns:
        Updated ConstraintResult with plugin violations included.
    """
    if not plugin_config:
        return result
    extra_violations: list[str] = []
    extra_metrics: dict = {}
    run_custom_checks(source_code, plugin_config, extra_violations, extra_metrics)
    if not extra_violations and not extra_metrics:
        return result
    all_violations = list(result.violations) + extra_violations
    all_metrics = {**result.metrics, **extra_metrics}
    return ConstraintResult(
        passed=len(all_violations) == 0,
        violations=all_violations,
        metrics=all_metrics,
    )


def _evaluate(source_code: str, cs: ConstraintSet) -> ConstraintResult:
    """Evaluate a single ConstraintSet against source code.

    Args:
        source_code: Python source code to analyze.
        cs: ConstraintSet to check against.

    Returns:
        ConstraintResult with pass/fail status and violations.
    """
    violations: list[str] = []
    metrics: dict = {}
    for checker in _CHECKERS:
        checker(source_code, cs, violations, metrics)
    return ConstraintResult(passed=len(violations) == 0, violations=violations, metrics=metrics)


def _chk_cyclomatic_complexity(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check cyclomatic complexity constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.max_cyclomatic_complexity is None:
        return
    max_cc, func_name = _max_cyclomatic_complexity(src)
    m["cyclomatic_complexity"] = max_cc
    if max_cc > cs.max_cyclomatic_complexity:
        v.append(
            f"Simplify '{func_name}' (complexity {max_cc})"
            f" — max {cs.max_cyclomatic_complexity}; extract branches into helpers"
        )


def _chk_lines_per_function(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check lines per function constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.max_lines_per_function is None:
        return
    max_lines, func_name = _max_function_lines(src, cs.count_docstrings_in_function_lines)
    m["lines_per_function"] = max_lines
    if max_lines > cs.max_lines_per_function:
        v.append(
            f"Split '{func_name}' ({max_lines} lines) into smaller helpers"
            f" — max {cs.max_lines_per_function} lines"
        )


def _chk_total_lines(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check total lines constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.max_total_lines is None:
        return
    total = len(src.splitlines())
    m["total_lines"] = total
    if total > cs.max_total_lines:
        v.append(f"Module too long ({total} lines) — max {cs.max_total_lines}; split into modules")


def _chk_docstrings(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check docstring requirement.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.require_docstrings is not True:
        return
    docstring_violations = _check_docstrings(src)
    m["missing_docstrings"] = docstring_violations
    v.extend(docstring_violations)


def _chk_time_complexity(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check time complexity constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.max_time_complexity is None:
        return
    estimated = _estimate_time_complexity(src)
    m["time_complexity"] = estimated
    if _complexity_rank(estimated) > _complexity_rank(cs.max_time_complexity):
        v.append(
            f"Time complexity {estimated} exceeds max {cs.max_time_complexity}"
            " — use a more efficient algorithm"
        )


def _chk_space_complexity(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check space complexity constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.max_space_complexity is None:
        return
    estimated = _estimate_space_complexity(src)
    m["space_complexity"] = estimated
    if _complexity_rank(estimated) > _complexity_rank(cs.max_space_complexity):
        v.append(
            f"Space complexity {estimated} exceeds max {cs.max_space_complexity}"
            " — reduce data structure allocations"
        )


def _chk_parameters(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check max parameters constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.max_parameters is None:
        return
    max_params, func_name = _max_parameters(src)
    m["max_parameters"] = max_params
    if max_params > cs.max_parameters:
        v.append(
            f"Reduce parameters in '{func_name}' ({max_params} params)"
            f" — max {cs.max_parameters}; group related params into a dataclass"
        )


def _chk_nested_depth(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check max nesting depth constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.max_nested_depth is None:
        return
    depth, func_name = _max_nesting_depth(src)
    m["max_nested_depth"] = depth
    if depth > cs.max_nested_depth:
        v.append(
            f"Reduce nesting in '{func_name}' (depth {depth})"
            f" — max {cs.max_nested_depth}; use early returns or extract helpers"
        )


def _chk_return_statements(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check max return statements constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.max_return_statements is None:
        return
    max_returns, func_name = _max_return_statements(src)
    m["max_return_statements"] = max_returns
    if max_returns > cs.max_return_statements:
        v.append(
            f"Reduce return paths in '{func_name}' ({max_returns} returns)"
            f" — max {cs.max_return_statements}"
        )


def _chk_print_statements(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no print statements constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_print_statements is not True:
        return
    prints = _find_print_calls(src)
    m["print_statements"] = prints
    for loc in prints:
        v.append(f"Remove print() at line {loc} — use logging instead")


def _chk_star_imports(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no star imports constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_star_imports is not True:
        return
    stars = _find_star_imports(src)
    m["star_imports"] = stars
    for mod in stars:
        v.append(f"Replace 'from {mod} import *' with explicit imports")


def _chk_mutable_defaults(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no mutable defaults constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_mutable_defaults is not True:
        return
    mutables = _find_mutable_defaults(src)
    m["mutable_defaults"] = mutables
    for name in mutables:
        v.append(f"In '{name}', replace mutable default with None and assign inside the body")


def _chk_global_state(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no global state constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_global_state is not True:
        return
    globals_found = _find_global_state(src)
    m["global_state"] = globals_found
    for name in globals_found:
        v.append(f"Move mutable global '{name}' into a function, or make it UPPER_CASE if constant")


def _chk_allowed_imports(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check allowed imports constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.allowed_imports is None:
        return
    forbidden = _check_imports(src, cs.allowed_imports)
    m["forbidden_imports"] = forbidden
    for imp in forbidden:
        v.append(f"Import '{imp}' is not in the allowed list — remove or use an allowed alternative")


def _chk_bare_except(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no bare except constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_bare_except is not True:
        return
    lines = _find_bare_excepts(src)
    m["bare_excepts"] = lines
    for ln in lines:
        v.append(f"Replace bare except at line {ln} with a specific exception type")


def _chk_try_except_pass(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no try-except-pass constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_try_except_pass is not True:
        return
    lines = _find_try_except_pass(src)
    m["try_except_pass"] = lines
    for ln in lines:
        v.append(f"Do not silence exceptions at line {ln} — log or re-raise instead of except/pass")


def _chk_return_in_finally(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no return in finally constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_return_in_finally is not True:
        return
    lines = _find_return_in_finally(src)
    m["return_in_finally"] = lines
    for ln in lines:
        v.append(f"Remove jump statement from finally block at line {ln} — it suppresses exceptions")


def _chk_unreachable_code(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no unreachable code constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_unreachable_code is not True:
        return
    lines = _find_unreachable_code(src)
    m["unreachable_code"] = lines
    for ln in lines:
        v.append(f"Remove unreachable code at line {ln} — it follows a return/raise/break")


def _chk_duplicate_dict_keys(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no duplicate dict keys constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_duplicate_dict_keys is not True:
        return
    lines = _find_duplicate_dict_keys(src)
    m["duplicate_dict_keys"] = lines
    for ln in lines:
        v.append(f"Remove duplicate dictionary key at line {ln}")


def _chk_loop_variable_closure(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no loop variable closure constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_loop_variable_closure is not True:
        return
    lines = _find_loop_closures(src)
    m["loop_variable_closures"] = lines
    for ln in lines:
        v.append(f"Closure at line {ln} captures loop variable — bind it via a default parameter")


def _chk_mutable_call_defaults(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no mutable call in defaults constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_mutable_call_in_defaults is not True:
        return
    names = _find_call_defaults(src)
    m["mutable_call_defaults"] = names
    for name in names:
        v.append(f"In '{name}', replace function call in default with None and assign inside the body")


def _chk_shadowing_builtins(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no shadowing builtins constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_shadowing_builtins is not True:
        return
    names = _find_shadowed_builtins(src)
    m["shadowed_builtins"] = names
    for name in names:
        v.append(f"Rename '{name}' — it shadows the Python builtin")


def _chk_open_without_with(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no open without context manager constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_open_without_context_manager is not True:
        return
    lines = _find_open_without_with(src)
    m["open_without_with"] = lines
    for ln in lines:
        v.append(f"Use 'with open(...)' at line {ln} instead of bare open()")


def _chk_eval(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no eval constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_eval is not True:
        return
    lines = _find_calls_by_name(src, "eval")
    m["eval_calls"] = lines
    for ln in lines:
        v.append(f"Replace eval() at line {ln} with ast.literal_eval() or explicit parsing")


def _chk_exec(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no exec constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_exec is not True:
        return
    lines = _find_calls_by_name(src, "exec")
    m["exec_calls"] = lines
    for ln in lines:
        v.append(f"Remove exec() at line {ln} — use explicit code instead")


def _chk_unsafe_deserialization(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no unsafe deserialization constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_unsafe_deserialization is not True:
        return
    lines = _find_unsafe_deser(src)
    m["unsafe_deserialization"] = lines
    for ln in lines:
        v.append(f"Unsafe deserialization at line {ln} — replace pickle/marshal with json")


def _chk_unsafe_yaml(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no unsafe yaml constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_unsafe_yaml is not True:
        return
    lines = _find_unsafe_yaml(src)
    m["unsafe_yaml"] = lines
    for ln in lines:
        v.append(f"Use yaml.safe_load() at line {ln} instead of yaml.load() without SafeLoader")


def _chk_shell_true(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no shell=True constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_shell_true is not True:
        return
    lines = _find_shell_true(src)
    m["shell_true"] = lines
    for ln in lines:
        v.append(f"Remove shell=True at line {ln} — pass command as a list to subprocess")


def _chk_hardcoded_secrets(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no hardcoded secrets constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_hardcoded_secrets is not True:
        return
    names = _find_hardcoded_secrets(src)
    m["hardcoded_secrets"] = names
    for name in names:
        v.append(f"Move secret '{name}' to an environment variable or config file")


def _chk_requests_no_timeout(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no requests without timeout constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_requests_without_timeout is not True:
        return
    lines = _find_requests_no_timeout(src)
    m["requests_no_timeout"] = lines
    for ln in lines:
        v.append(f"Add timeout= parameter to HTTP request at line {ln}")


def _chk_cognitive_complexity(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check cognitive complexity constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.max_cognitive_complexity is None:
        return
    max_cc, func_name = _max_cognitive_complexity(src)
    m["cognitive_complexity"] = max_cc
    if max_cc > cs.max_cognitive_complexity:
        v.append(
            f"Simplify '{func_name}' (cognitive complexity {max_cc})"
            f" — max {cs.max_cognitive_complexity}; break into smaller functions"
        )


def _chk_local_variables(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check max local variables constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.max_local_variables is None:
        return
    max_locals, func_name = _max_local_variables(src)
    m["max_local_variables"] = max_locals
    if max_locals > cs.max_local_variables:
        v.append(
            f"Reduce locals in '{func_name}' ({max_locals} vars)"
            f" — max {cs.max_local_variables}; extract helpers"
        )


def _chk_debugger_statements(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no debugger statements constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_debugger_statements is not True:
        return
    lines = _find_debugger_stmts(src)
    m["debugger_statements"] = lines
    for ln in lines:
        v.append(f"Remove debugger statement at line {ln}")


def _chk_nested_imports(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no nested imports constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_nested_imports is not True:
        return
    lines = _find_nested_imports(src)
    m["nested_imports"] = lines
    for ln in lines:
        v.append(f"Nested import at line {ln} — move to the module top level")


def _chk_type_annotations(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check require type annotations constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.require_type_annotations is not True:
        return
    names = _find_unannotated_fns(src)
    m["unannotated_functions"] = names
    for name in names:
        v.append(f"Add type annotations to '{name}' — annotate parameters and return type")


def _chk_magic_numbers(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check no magic numbers constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.no_magic_numbers is not True:
        return
    magic = _find_magic_numbers(src)
    m["magic_numbers"] = magic
    for lineno, value in magic:
        v.append(f"Extract magic number {value} at line {lineno} into a named constant")


def _chk_string_literal_repeats(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    """Check repeated string literal constraint.

    Args:
        src: Source code.
        cs: Constraint set.
        v: Violations list.
        m: Metrics dict.
    """
    if cs.max_string_literal_repeats is None:
        return
    repeated = _find_repeated_strings(src, cs.max_string_literal_repeats)
    m["repeated_string_literals"] = repeated
    for value, count in repeated:
        v.append(
            f"String {value!r} repeated {count} times"
            f" (max {cs.max_string_literal_repeats}) — extract into a constant"
        )


_CHECKERS = [
    _chk_cyclomatic_complexity,
    _chk_lines_per_function,
    _chk_total_lines,
    _chk_docstrings,
    _chk_time_complexity,
    _chk_space_complexity,
    _chk_parameters,
    _chk_nested_depth,
    _chk_return_statements,
    _chk_print_statements,
    _chk_star_imports,
    _chk_mutable_defaults,
    _chk_global_state,
    _chk_allowed_imports,
    _chk_bare_except,
    _chk_try_except_pass,
    _chk_return_in_finally,
    _chk_unreachable_code,
    _chk_duplicate_dict_keys,
    _chk_loop_variable_closure,
    _chk_mutable_call_defaults,
    _chk_shadowing_builtins,
    _chk_open_without_with,
    _chk_eval,
    _chk_exec,
    _chk_unsafe_deserialization,
    _chk_unsafe_yaml,
    _chk_shell_true,
    _chk_hardcoded_secrets,
    _chk_requests_no_timeout,
    _chk_cognitive_complexity,
    _chk_local_variables,
    _chk_debugger_statements,
    _chk_nested_imports,
    _chk_type_annotations,
    _chk_magic_numbers,
    _chk_string_literal_repeats,
]


def _max_cyclomatic_complexity(source_code: str) -> tuple[int, str]:
    """Return the maximum cyclomatic complexity and offending function name.

    Args:
        source_code: Python source code to analyze.

    Returns:
        Tuple of (max_complexity, function_name).
    """
    blocks = cc_visit(source_code)
    if not blocks:
        return 1, ""
    worst = max(blocks, key=lambda b: b.complexity)
    return worst.complexity, worst.name


def _max_function_lines(
    source_code: str, count_docstrings: bool = True,
) -> tuple[int, str]:
    """Return the maximum function line count and offending function name.

    Args:
        source_code: Python source code to analyze.
        count_docstrings: Whether to include docstring lines in the count.

    Returns:
        Tuple of (max_lines, function_name).
    """
    tree = ast.parse(source_code)
    max_lines = 0
    max_name = ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_lines = node.end_lineno - node.lineno + 1
            if not count_docstrings:
                func_lines -= _docstring_line_count(node)
            if func_lines > max_lines:
                max_lines = func_lines
                max_name = node.name
    return max_lines, max_name


def _docstring_line_count(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Return the number of lines occupied by a function's docstring.

    Args:
        node: Function definition AST node.

    Returns:
        Line count of the docstring, or 0 if none.
    """
    if not node.body:
        return 0
    first = node.body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return first.end_lineno - first.lineno + 1
    return 0


def _check_docstrings(source_code: str) -> list[str]:
    """Return names of functions/classes with invalid or missing docstrings.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of violation messages for docstring issues.
    """
    tree = ast.parse(source_code)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            issue = _get_docstring_issue(node)
            if issue:
                violations.append(issue)
    return violations


def _get_docstring_issue(node: ast.AST) -> str | None:
    """Get the docstring issue for an AST node, if any.

    Args:
        node: AST node to check.

    Returns:
        Error message if there's a docstring issue, None otherwise.
    """
    body = getattr(node, "body", [])
    if not body:
        return f"Add docstring to '{node.name}'"

    first = body[0]
    if not (
        isinstance(first, ast.Expr)
        and isinstance(first.value, (ast.Constant,))
        and isinstance(first.value.value, str)
    ):
        return f"Add docstring to '{node.name}'"

    docstring = first.value.value

    # For classes, just require a docstring to exist
    if isinstance(node, ast.ClassDef):
        return None

    # For functions, check if Args: and Returns: sections are needed
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        # Check if function has parameters (excluding self/cls)
        params = [arg.arg for arg in node.args.args if arg.arg not in (_SELF_ARG, _CLS_ARG)]
        needs_args = len(params) > 0

        # Check if function has a return statement with a value
        needs_returns = _has_return_value(node)

        # Check for Args: section if needed
        if needs_args and "Args:" not in docstring:
            return f"Add Args section to '{node.name}' docstring"

        # Check for Returns: section if needed
        if needs_returns and "Returns:" not in docstring:
            return f"Add Returns section to '{node.name}' docstring"

    return None


def _has_return_value(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Check if a function has a return statement with a value.

    Args:
        node: Function AST node to check.

    Returns:
        True if function returns a value, False otherwise.
    """
    for child in ast.walk(node):
        if isinstance(child, ast.Return) and child.value is not None:
            return True
    return False


def _check_imports(source_code: str, allowed: list[str]) -> list[str]:
    """Return import names not in the allowed list.

    Args:
        source_code: Python source code to analyze.
        allowed: List of allowed import names.

    Returns:
        List of forbidden import names.
    """
    tree = ast.parse(source_code)
    forbidden: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in allowed:
                    forbidden.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.module not in allowed:
            forbidden.append(node.module)
    return forbidden


_COMPLEXITY_ORDER = {
    "O(1)": 0,
    "O(log n)": 1,
    "O(n)": 2,
    "O(n log n)": 3,
    "O(n^2)": 4,
    "O(n^3)": 5,
    "O(2^n)": 6,
}

_NESTING_TO_COMPLEXITY = {
    0: "O(1)",
    1: "O(n)",
    2: "O(n^2)",
    3: "O(n^3)",
}

_EXPENSIVE_METHOD_DEPTH: dict[str, int] = {
    "sort": 1, "index": 1, "count": 1, "remove": 1,
}

_EXPENSIVE_BUILTIN_DEPTH: dict[str, int] = {
    "sorted": 1, "sum": 1, "min": 1, "max": 1, "any": 1, "all": 1,
}

_FUNC_NODE_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)
_LOOP_NODE_TYPES = (ast.For, ast.While)
_COMP_NODE_TYPES = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _complexity_rank(complexity: str) -> int:
    """Map a complexity string to a comparable rank.

    Args:
        complexity: Big-O notation string.

    Returns:
        Integer rank for comparison.
    """
    return _COMPLEXITY_ORDER.get(complexity, len(_COMPLEXITY_ORDER))


def _estimate_time_complexity(source_code: str) -> str:
    """Estimate time complexity from loop depth, expensive ops, and recursion.

    Args:
        source_code: Python source code to analyze.

    Returns:
        Big-O notation string.
    """
    tree = ast.parse(source_code)
    max_depth = 0
    for node in ast.walk(tree):
        if isinstance(node, _FUNC_NODE_TYPES):
            max_depth = max(max_depth, _function_time_depth(node))
    return _NESTING_TO_COMPLEXITY.get(max_depth, f"O(n^{max_depth})")


def _function_time_depth(func_node: ast.AST) -> int:
    """Compute the effective time complexity depth for a function.

    Args:
        func_node: Function definition AST node.

    Returns:
        Effective depth (0=O(1), 1=O(n), 2=O(n^2), etc).
    """
    func_name = getattr(func_node, "name", "")
    depth = _max_effective_depth(func_node, 0, func_name)
    if _detects_self_call(func_node, func_name) and depth < 1:
        depth = 1
    return depth


def _max_effective_depth(node: ast.AST, loop_depth: int, func_name: str) -> int:
    """Recursively compute effective depth considering loops, ops, and comprehensions.

    Args:
        node: AST node to inspect.
        loop_depth: Current loop nesting depth.
        func_name: Enclosing function name for recursion skip.

    Returns:
        Maximum effective depth found in this subtree.
    """
    best = loop_depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _FUNC_NODE_TYPES):
            continue
        if isinstance(child, _LOOP_NODE_TYPES):
            best = max(best, _max_effective_depth(child, loop_depth + 1, func_name))
        elif isinstance(child, _COMP_NODE_TYPES):
            comp_depth = loop_depth + len(child.generators)
            best = max(best, _max_effective_depth(child, comp_depth, func_name))
        elif isinstance(child, ast.Call) and loop_depth > 0:
            best = max(best, loop_depth + _call_depth_cost(child))
            best = max(best, _max_effective_depth(child, loop_depth, func_name))
        elif isinstance(child, ast.Compare) and loop_depth > 0:
            if any(isinstance(op, (ast.In, ast.NotIn)) for op in child.ops):
                best = max(best, loop_depth + 1)
            best = max(best, _max_effective_depth(child, loop_depth, func_name))
        else:
            best = max(best, _max_effective_depth(child, loop_depth, func_name))
    return best


def _call_depth_cost(node: ast.Call) -> int:
    """Return extra depth cost of a function/method call.

    Args:
        node: AST Call node.

    Returns:
        Additional depth (0 if the call is O(1)).
    """
    if isinstance(node.func, ast.Attribute):
        return _EXPENSIVE_METHOD_DEPTH.get(node.func.attr, 0)
    if isinstance(node.func, ast.Name):
        return _EXPENSIVE_BUILTIN_DEPTH.get(node.func.id, 0)
    return 0


def _detects_self_call(func_node: ast.AST, func_name: str) -> bool:
    """Check if a function body contains a direct recursive call.

    Args:
        func_node: Function definition AST node.
        func_name: Name of the function to look for.

    Returns:
        True if the function calls itself.
    """
    if not func_name:
        return False
    for child in ast.walk(func_node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == func_name
        ):
            return True
    return False


_GROWING_METHODS = frozenset({"append", "extend", "add", "insert"})
_MATERIALIZING_BUILTINS = frozenset({"list", "dict", "set", "frozenset", "tuple"})
_COPY_METHODS = frozenset({"copy", "deepcopy"})


def _estimate_space_complexity(source_code: str) -> str:
    """Estimate space complexity from allocations, comprehensions, and loops.

    Args:
        source_code: Python source code to analyze.

    Returns:
        Big-O notation string.
    """
    tree = ast.parse(source_code)
    max_depth = 0
    for node in ast.walk(tree):
        if isinstance(node, _FUNC_NODE_TYPES):
            max_depth = max(max_depth, _function_space_depth(node))
    return _NESTING_TO_COMPLEXITY.get(max_depth, f"O(n^{max_depth})")


def _function_space_depth(func_node: ast.AST) -> int:
    """Compute effective space depth for a function.

    Args:
        func_node: Function definition AST node.

    Returns:
        Space depth (0=O(1), 1=O(n), 2=O(n^2), etc).
    """
    best = _space_walk(func_node)
    best = max(best, _space_from_loops(func_node, 0))
    return best


def _space_walk(node: ast.AST) -> int:
    """Walk AST for space-allocating patterns, skipping into nested comps.

    Args:
        node: AST node to inspect.

    Returns:
        Maximum space depth found in the subtree.
    """
    best = 0
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _FUNC_NODE_TYPES):
            continue
        if isinstance(child, _COMP_NODE_TYPES):
            best = max(best, _comprehension_space_depth(child))
        elif isinstance(child, ast.Call):
            best = max(best, _call_space_cost(child))
            best = max(best, _space_walk(child))
        elif isinstance(child, ast.Subscript) and isinstance(child.slice, ast.Slice):
            best = max(best, 1)
        else:
            best = max(best, _space_walk(child))
    return best


def _comprehension_space_depth(node: ast.AST) -> int:
    """Compute space depth from a comprehension node, including nested comps.

    Args:
        node: ListComp, SetComp, DictComp, or GeneratorExp AST node.

    Returns:
        Space depth accounting for nested materializing comprehensions.
    """
    if isinstance(node, ast.GeneratorExp):
        return 0
    own = len(node.generators)
    inner_max = 0
    elt = getattr(node, "elt", None) or getattr(node, "value", None)
    if elt is not None:
        for child in ast.walk(elt):
            if isinstance(child, _COMP_NODE_TYPES) and child is not node:
                inner_max = max(inner_max, _comprehension_space_depth(child))
    return own + inner_max


def _call_space_cost(node: ast.Call) -> int:
    """Return space cost of a single call (materialization or copy).

    Args:
        node: AST Call node.

    Returns:
        Space depth contribution (0 or 1).
    """
    if isinstance(node.func, ast.Name) and node.func.id in _MATERIALIZING_BUILTINS:
        if node.args:
            return 1
        return 0
    if isinstance(node.func, ast.Attribute) and node.func.attr in _COPY_METHODS:
        return 1
    return 0


def _space_from_loops(node: ast.AST, loop_depth: int) -> int:
    """Detect growing collections inside loops for space depth.

    Args:
        node: AST node to inspect.
        loop_depth: Current loop nesting depth.

    Returns:
        Maximum space depth from grow-in-loop patterns.
    """
    best = 0
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _FUNC_NODE_TYPES):
            continue
        if isinstance(child, _LOOP_NODE_TYPES):
            best = max(best, _space_from_loops(child, loop_depth + 1))
        elif isinstance(child, ast.Call) and loop_depth > 0:
            if _is_growing_call(child):
                best = max(best, loop_depth)
            best = max(best, _space_from_loops(child, loop_depth))
        else:
            best = max(best, _space_from_loops(child, loop_depth))
    return best


def _is_growing_call(node: ast.Call) -> bool:
    """Check if a Call node is a collection-growing method.

    Args:
        node: AST Call node.

    Returns:
        True if the call grows a collection (append, extend, add, insert).
    """
    return isinstance(node.func, ast.Attribute) and node.func.attr in _GROWING_METHODS


def _max_parameters(source_code: str) -> tuple[int, str]:
    """Return the maximum parameter count and offending function name.

    Args:
        source_code: Python source code to analyze.

    Returns:
        Tuple of (max_params, function_name).
    """
    tree = ast.parse(source_code)
    max_params = 0
    max_name = ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params = [a.arg for a in node.args.args if a.arg not in ("self", "cls")]
            if len(params) > max_params:
                max_params = len(params)
                max_name = node.name
    return max_params, max_name


def _max_nesting_depth(source_code: str) -> tuple[int, str]:
    """Return the maximum nesting depth and offending function name.

    Args:
        source_code: Python source code to analyze.

    Returns:
        Tuple of (max_depth, function_name).
    """
    tree = ast.parse(source_code)
    max_depth = 0
    max_name = ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            depth = _walk_nesting(node, 0)
            if depth > max_depth:
                max_depth = depth
                max_name = node.name
    return max_depth, max_name


def _walk_nesting(node: ast.AST, current: int) -> int:
    """Recursively find the maximum control flow nesting depth.

    Args:
        node: AST node to inspect.
        current: Current nesting depth.

    Returns:
        Maximum nesting depth found.
    """
    _nesting_types = (ast.If, ast.For, ast.While, ast.Try, ast.With)
    max_depth = current
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _nesting_types):
            max_depth = max(max_depth, _walk_nesting(child, current + 1))
        else:
            max_depth = max(max_depth, _walk_nesting(child, current))
    return max_depth


def _max_return_statements(source_code: str) -> tuple[int, str]:
    """Return the maximum return count and offending function name.

    Args:
        source_code: Python source code to analyze.

    Returns:
        Tuple of (max_returns, function_name).
    """
    tree = ast.parse(source_code)
    max_returns = 0
    max_name = ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            count = sum(1 for child in ast.walk(node) if isinstance(child, ast.Return))
            if count > max_returns:
                max_returns = count
                max_name = node.name
    return max_returns, max_name


def _find_print_calls(source_code: str) -> list[int]:
    """Find line numbers of print() calls.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of line numbers where print() is called.
    """
    tree = ast.parse(source_code)
    lines = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            lines.append(node.lineno)
    return lines


def _find_star_imports(source_code: str) -> list[str]:
    """Find modules imported with wildcard.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of module names with star imports.
    """
    tree = ast.parse(source_code)
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    modules.append(node.module or "")
    return modules


def _find_mutable_defaults(source_code: str) -> list[str]:
    """Find functions with mutable default arguments.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of function names with mutable defaults.
    """
    tree = ast.parse(source_code)
    names = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for default in node.args.defaults + node.args.kw_defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    names.append(node.name)
                    break
    return names


def _find_global_state(source_code: str) -> list[str]:
    """Find module-level mutable variable assignments.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of variable names that represent mutable global state.
    """
    tree = ast.parse(source_code)
    names = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                # Skip UPPER_CASE names (constants by convention)
                if isinstance(target, ast.Name) and target.id != target.id.upper():
                    names.append(target.id)
    return names


# --- Correctness helpers ---


def _find_bare_excepts(source_code: str) -> list[int]:
    """Find line numbers of bare except clauses.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of line numbers with bare except.
    """
    tree = ast.parse(source_code)
    return [
        n.lineno for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and n.type is None
    ]


def _find_try_except_pass(source_code: str) -> list[int]:
    """Find line numbers of except clauses with only pass.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of line numbers with except/pass.
    """
    tree = ast.parse(source_code)
    lines = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ExceptHandler)
            and len(node.body) == 1
            and isinstance(node.body[0], ast.Pass)
        ):
            lines.append(node.lineno)
    return lines


def _find_return_in_finally(source_code: str) -> list[int]:
    """Find return/break/continue statements inside finally blocks.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of line numbers of jump statements in finally.
    """
    tree = ast.parse(source_code)
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for stmt in node.finalbody:
                for child in _walk_skip_functions(stmt):
                    if isinstance(child, (ast.Return, ast.Break, ast.Continue)):
                        lines.append(child.lineno)
    return lines


def _walk_skip_functions(node: ast.AST):
    """Walk AST nodes without entering nested function definitions.

    Args:
        node: Starting AST node.

    Yields:
        AST nodes excluding nested function internals.
    """
    yield node
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield from _walk_skip_functions(child)


def _find_unreachable_code(source_code: str) -> list[int]:
    """Find statements after return/raise/break/continue.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of line numbers of unreachable statements.
    """
    tree = ast.parse(source_code)
    lines = []
    terminal = (ast.Return, ast.Raise, ast.Break, ast.Continue)
    for node in ast.walk(tree):
        for attr in ("body", "orelse", "finalbody"):
            stmts = getattr(node, attr, None)
            if not isinstance(stmts, list):
                continue
            for i, stmt in enumerate(stmts):
                if isinstance(stmt, terminal) and i < len(stmts) - 1:
                    lines.append(stmts[i + 1].lineno)
    return lines


def _find_duplicate_dict_keys(source_code: str) -> list[int]:
    """Find duplicate constant keys in dictionary literals.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of line numbers with duplicate keys.
    """
    tree = ast.parse(source_code)
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        seen: set = set()
        for key in node.keys:
            if key is None:
                continue
            if isinstance(key, ast.Constant) and key.value in seen:
                lines.append(key.lineno)
            elif isinstance(key, ast.Constant):
                seen.add(key.value)
    return lines


def _find_loop_closures(source_code: str) -> list[int]:
    """Find closures inside for-loops that capture the loop variable.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of line numbers of unsafe closures.
    """
    tree = ast.parse(source_code)
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        loop_vars = _extract_target_names(node.target)
        for child in ast.walk(node):
            if child is node:
                continue
            if not isinstance(child, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if _closure_uses_loop_var(child, loop_vars):
                lines.append(child.lineno)
    return lines


def _extract_target_names(target: ast.AST) -> set[str]:
    """Extract variable names from an assignment target.

    Args:
        target: AST assignment target node.

    Returns:
        Set of variable name strings.
    """
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for elt in target.elts:
            names.update(_extract_target_names(elt))
        return names
    return set()


def _closure_uses_loop_var(node: ast.AST, loop_vars: set[str]) -> bool:
    """Check if a closure references loop variables without capturing them.

    Args:
        node: Lambda or function definition node.
        loop_vars: Set of loop variable names to check.

    Returns:
        True if the closure unsafely references a loop variable.
    """
    defaults = _get_default_names(node)
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in loop_vars and child.id not in defaults:
            return True
    return False


def _get_default_names(node: ast.AST) -> set[str]:
    """Get parameter names that have default values.

    Args:
        node: Lambda or function definition node.

    Returns:
        Set of parameter names with defaults.
    """
    args = getattr(node, "args", None)
    if args is None:
        return set()
    names: set[str] = set()
    n_defaults = len(args.defaults)
    n_args = len(args.args)
    for i in range(n_defaults):
        names.add(args.args[n_args - n_defaults + i].arg)
    return names


_SAFE_CALL_DEFAULTS = frozenset(
    {
        "frozenset",
        "tuple",
        "bytes",
        "int",
        "float",
        "str",
        "bool",
        "complex",
        "Field",
        "field",
        "dataclass",
        "property",
    }
)


def _find_call_defaults(source_code: str) -> list[str]:
    """Find functions with function calls in default arguments.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of function names with call defaults.
    """
    tree = ast.parse(source_code)
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for default in node.args.defaults + node.args.kw_defaults:
            if default is None:
                continue
            if (
                isinstance(default, ast.Call)
                and _get_call_name(default) not in _SAFE_CALL_DEFAULTS
            ):
                names.append(node.name)
                break
    return names


def _get_call_name(node: ast.Call) -> str:
    """Extract the function name from a Call node.

    Args:
        node: AST Call node.

    Returns:
        Function name string, or empty string if unresolvable.
    """
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


_BUILTIN_NAMES = frozenset(dir(builtins)) - frozenset(
    {
        "__name__",
        "__doc__",
        "__package__",
        "__loader__",
        "__spec__",
        "__builtins__",
        "__file__",
        "__cached__",
        "None",
        "True",
        "False",
        "__build_class__",
        "__import__",
    }
)


def _find_shadowed_builtins(source_code: str) -> list[str]:
    """Find variable/function names that shadow Python builtins.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of shadowed builtin names.
    """
    tree = ast.parse(source_code)
    shadows: list[str] = []
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in _BUILTIN_NAMES and node.name not in seen:
                shadows.append(node.name)
                seen.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id in _BUILTIN_NAMES
                    and target.id not in seen
                ):
                    shadows.append(target.id)
                    seen.add(target.id)
    return shadows


def _find_open_without_with(source_code: str) -> list[int]:
    """Find open() calls not used as context managers.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of line numbers of bare open() calls.
    """
    tree = ast.parse(source_code)
    with_opens: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            for item in node.items:
                if _is_open_call(item.context_expr):
                    with_opens.add(id(item.context_expr))
    lines = []
    for node in ast.walk(tree):
        if _is_open_call(node) and id(node) not in with_opens:
            lines.append(node.lineno)
    return lines


def _is_open_call(node: ast.AST) -> bool:
    """Check if an AST node is a call to open().

    Args:
        node: AST node to check.

    Returns:
        True if the node is an open() call.
    """
    return (
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open"
    )


# --- Security helpers ---


def _find_calls_by_name(source_code: str, name: str) -> list[int]:
    """Find line numbers of calls to a specific function name.

    Args:
        source_code: Python source code to analyze.
        name: Function name to search for.

    Returns:
        List of line numbers where the function is called.
    """
    tree = ast.parse(source_code)
    return [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name
    ]


_UNSAFE_DESER_ATTRS = frozenset({"load", "loads", "Unpickler"})
_UNSAFE_DESER_MODULES = frozenset({"pickle", "marshal"})


def _find_unsafe_deser(source_code: str) -> list[int]:
    """Find unsafe deserialization calls (pickle/marshal).

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of line numbers with unsafe deserialization.
    """
    tree = ast.parse(source_code)
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in _UNSAFE_DESER_ATTRS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in _UNSAFE_DESER_MODULES
        ):
            lines.append(node.lineno)
    return lines


def _find_unsafe_yaml(source_code: str) -> list[int]:
    """Find yaml.load() calls without SafeLoader.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of line numbers with unsafe yaml.load().
    """
    tree = ast.parse(source_code)
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "load"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "yaml"
        ):
            continue
        has_loader = any(kw.arg == "Loader" for kw in node.keywords)
        if not has_loader:
            lines.append(node.lineno)
    return lines


def _find_shell_true(source_code: str) -> list[int]:
    """Find subprocess calls with shell=True.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of line numbers with shell=True.
    """
    tree = ast.parse(source_code)
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                lines.append(node.lineno)
                break
    return lines


_SECRET_PATTERNS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "access_key",
        "secret_key",
        "private_key",
    }
)


def _find_hardcoded_secrets(source_code: str) -> list[str]:
    """Find variables with secret-like names assigned string literals.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of variable names containing hardcoded secrets.
    """
    tree = ast.parse(source_code)
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if (
                target.id.lower() in _SECRET_PATTERNS
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                names.append(target.id)
    return names


_REQUEST_METHODS = frozenset({"get", "post", "put", "delete", "patch", "head", "options"})


def _find_requests_no_timeout(source_code: str) -> list[int]:
    """Find HTTP request calls without a timeout parameter.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of line numbers of requests without timeout.
    """
    tree = ast.parse(source_code)
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in _REQUEST_METHODS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "requests"
        ):
            continue
        has_timeout = any(kw.arg == "timeout" for kw in node.keywords)
        if not has_timeout:
            lines.append(node.lineno)
    return lines


# --- Maintainability helpers ---


def _max_cognitive_complexity(source_code: str) -> tuple[int, str]:
    """Return the maximum cognitive complexity and offending function name.

    Args:
        source_code: Python source code to analyze.

    Returns:
        Tuple of (max_complexity, function_name).
    """
    tree = ast.parse(source_code)
    max_cc = 0
    max_name = ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cc = _cognitive_for_node(node, 0)
            if cc > max_cc:
                max_cc = cc
                max_name = node.name
    return max_cc, max_name


def _cognitive_for_node(node: ast.AST, nesting: int) -> int:
    """Compute cognitive complexity for an AST subtree.

    Args:
        node: AST node to analyze.
        nesting: Current nesting depth.

    Returns:
        Cognitive complexity score.
    """
    total = 0
    for child in ast.iter_child_nodes(node):
        total += _cognitive_score(child, nesting)
    return total


def _cognitive_score(child: ast.AST, nesting: int) -> int:
    """Score a single AST node for cognitive complexity.

    Args:
        child: AST node to score.
        nesting: Current nesting depth.

    Returns:
        Cognitive complexity contribution of this node.
    """
    if isinstance(child, ast.If):
        return _cognitive_for_if(child, nesting)
    if isinstance(child, (ast.For, ast.While)):
        score = 1 + nesting
        return score + _cognitive_for_node(child, nesting + 1)
    if isinstance(child, ast.BoolOp):
        return 1 + _cognitive_for_node(child, nesting)
    if isinstance(child, ast.IfExp):
        return 1 + nesting + _cognitive_for_node(child, nesting)
    if isinstance(child, ast.Try):
        return _cognitive_for_try(child, nesting)
    if isinstance(child, (ast.Break, ast.Continue)):
        return 1
    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        return _cognitive_for_node(child, nesting + 1)
    return _cognitive_for_node(child, nesting)


def _cognitive_for_if(node: ast.If, nesting: int) -> int:
    """Compute cognitive complexity for an if/elif/else chain.

    Args:
        node: If AST node.
        nesting: Current nesting depth.

    Returns:
        Cognitive complexity for the entire if chain.
    """
    score = 1 + nesting
    score += _cognitive_for_node_stmts(node.body, nesting + 1)
    orelse = node.orelse
    if orelse:
        if len(orelse) == 1 and isinstance(orelse[0], ast.If):
            score += 1 + _cognitive_for_if_body(orelse[0], nesting)
        else:
            score += 1 + _cognitive_for_node_stmts(orelse, nesting + 1)
    return score


def _cognitive_for_if_body(node: ast.If, nesting: int) -> int:
    """Compute cognitive complexity for an elif branch.

    Args:
        node: If AST node representing an elif.
        nesting: Current nesting depth.

    Returns:
        Cognitive complexity for elif and its continuations.
    """
    score = _cognitive_for_node_stmts(node.body, nesting + 1)
    orelse = node.orelse
    if orelse:
        if len(orelse) == 1 and isinstance(orelse[0], ast.If):
            score += 1 + _cognitive_for_if_body(orelse[0], nesting)
        else:
            score += 1 + _cognitive_for_node_stmts(orelse, nesting + 1)
    return score


def _cognitive_for_try(node: ast.Try, nesting: int) -> int:
    """Compute cognitive complexity for a try/except block.

    Args:
        node: Try AST node.
        nesting: Current nesting depth.

    Returns:
        Cognitive complexity for the try block.
    """
    score = _cognitive_for_node_stmts(node.body, nesting)
    for handler in node.handlers:
        score += 1 + nesting + _cognitive_for_node_stmts(handler.body, nesting + 1)
    score += _cognitive_for_node_stmts(node.orelse, nesting)
    score += _cognitive_for_node_stmts(node.finalbody, nesting)
    return score


def _cognitive_for_node_stmts(stmts: list, nesting: int) -> int:
    """Compute cognitive complexity for a list of statements.

    Args:
        stmts: List of AST statement nodes.
        nesting: Current nesting depth.

    Returns:
        Total cognitive complexity for the statements.
    """
    total = 0
    for stmt in stmts:
        total += _cognitive_score(stmt, nesting)
    return total


def _max_local_variables(source_code: str) -> tuple[int, str]:
    """Return the maximum local variable count and offending function name.

    Args:
        source_code: Python source code to analyze.

    Returns:
        Tuple of (max_locals, function_name).
    """
    tree = ast.parse(source_code)
    max_locals = 0
    max_name = ""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = _get_param_names(node)
        locals_set: set[str] = set()
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Name)
                and isinstance(child.ctx, ast.Store)
                and child.id not in params
            ):
                locals_set.add(child.id)
        if len(locals_set) > max_locals:
            max_locals = len(locals_set)
            max_name = node.name
    return max_locals, max_name


def _get_param_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Get all parameter names for a function.

    Args:
        node: Function definition node.

    Returns:
        Set of parameter name strings.
    """
    names = {a.arg for a in node.args.args}
    names.update(a.arg for a in node.args.kwonlyargs)
    if node.args.vararg:
        names.add(node.args.vararg.arg)
    if node.args.kwarg:
        names.add(node.args.kwarg.arg)
    return names


def _find_debugger_stmts(source_code: str) -> list[int]:
    """Find debugger imports and breakpoint() calls.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of line numbers with debugger statements.
    """
    tree = ast.parse(source_code)
    debuggers = {"pdb", "ipdb", "pudb"}
    lines = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "breakpoint"
        ):
            lines.append(node.lineno)
        elif isinstance(node, ast.Import):
            if any(a.name in debuggers for a in node.names):
                lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module in debuggers:
            lines.append(node.lineno)
    return lines


def _find_nested_imports(source_code: str) -> list[int]:
    """Find import statements inside functions.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of line numbers of nested imports.
    """
    tree = ast.parse(source_code)
    lines = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(func):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                lines.append(child.lineno)
    return lines


def _find_unannotated_fns(source_code: str) -> list[str]:
    """Find functions missing type annotations.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of function names without complete annotations.
    """
    tree = ast.parse(source_code)
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.returns is None:
            names.append(node.name)
            continue
        for arg in node.args.args:
            if arg.arg in (_SELF_ARG, _CLS_ARG):
                continue
            if arg.annotation is None:
                names.append(node.name)
                break
    return names


_SELF_ARG = "self"
_CLS_ARG = "cls"
_EXEMPT_MAGIC_VALUES = frozenset({-1, 0, 1, 2})
_FIELD_EXEMPT_KWARGS = frozenset({"ge", "le", "gt", "lt"})


def _is_numeric(value: object) -> bool:
    """Check if a value is numeric (int or float) but not bool.

    Args:
        value: Value to check.

    Returns:
        True if value is int or float and not bool.
    """
    if type(value) is bool:
        return False
    return isinstance(value, (int, float))


def _is_field_call(node: ast.Call) -> bool:
    """Check if a Call node invokes Pydantic Field().

    Args:
        node: AST Call node.

    Returns:
        True if the call is to Field().
    """
    if isinstance(node.func, ast.Name) and node.func.id == "Field":
        return True
    return isinstance(node.func, ast.Attribute) and node.func.attr == "Field"


def _add_numeric_ids(root: ast.AST, exempt: set[int]) -> None:
    """Add id() of all numeric Constant nodes under root to exempt set.

    Args:
        root: AST subtree to walk.
        exempt: Set to collect exempt constant ids into.
    """
    for c in ast.walk(root):
        if isinstance(c, ast.Constant) and _is_numeric(c.value):
            exempt.add(id(c))


def _exempt_module_constants(tree: ast.Module, exempt: set[int]) -> None:
    """Exempt numeric constants in module-level UPPER_CASE assignments.

    Args:
        tree: Parsed AST module.
        exempt: Set to collect exempt constant ids into.
    """
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and all(
            isinstance(t, ast.Name) and t.id == t.id.upper() and t.id != t.id.lower()
            for t in stmt.targets
        ):
            _add_numeric_ids(stmt.value, exempt)
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            name = stmt.target.id
            if name == name.upper() and name != name.lower() and stmt.value is not None:
                _add_numeric_ids(stmt.value, exempt)


def _exempt_field_and_structural(tree: ast.Module, exempt: set[int]) -> None:
    """Exempt numerics in Field() kwargs, subscripts, and power exponents.

    Args:
        tree: Parsed AST module.
        exempt: Set to collect exempt constant ids into.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_field_call(node):
            for kw in node.keywords:
                if kw.arg in _FIELD_EXEMPT_KWARGS:
                    _add_numeric_ids(kw.value, exempt)
        if isinstance(node, ast.Subscript):
            _add_numeric_ids(node.slice, exempt)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            _add_numeric_ids(node.right, exempt)


def _collect_exempt_constant_ids(tree: ast.Module) -> set[int]:
    """Collect id() values of numeric constants in exempt AST contexts.

    Args:
        tree: Parsed AST module.

    Returns:
        Set of id() values for Constant nodes that should not be flagged.
    """
    exempt: set[int] = set()
    _exempt_module_constants(tree, exempt)
    _exempt_field_and_structural(tree, exempt)
    return exempt


def _find_magic_numbers(source_code: str) -> list[tuple[int, int | float]]:
    """Find magic number literals inside function and method bodies.

    A magic number is any numeric literal (int or float, not bool) that is not
    in {-1, 0, 1, 2} and does not appear in an exempt context such as
    module-level UPPER_CASE assignments, Pydantic Field kwargs, slices, or
    power exponents.

    Args:
        source_code: Python source code to analyze.

    Returns:
        List of (line_number, value) tuples for each magic number found.
    """
    tree = ast.parse(source_code)
    exempt_ids = _collect_exempt_constant_ids(tree)
    results: list[tuple[int, int | float]] = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for stmt in func.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for child in ast.walk(stmt):
                if not isinstance(child, ast.Constant):
                    continue
                if not _is_numeric(child.value):
                    continue
                if child.value in _EXEMPT_MAGIC_VALUES:
                    continue
                if id(child) in exempt_ids:
                    continue
                results.append((child.lineno, child.value))
    return results


def _exempt_docstring_strings(tree: ast.Module, exempt: set[int]) -> None:
    """Mark docstring constants as exempt from string literal counting.

    Args:
        tree: Parsed AST module.
        exempt: Set to collect exempt constant ids into.
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            exempt.add(id(first.value))


def _exempt_upper_case_strings(tree: ast.Module, exempt: set[int]) -> None:
    """Mark strings in module-level UPPER_CASE assignments as exempt.

    Args:
        tree: Parsed AST module.
        exempt: Set to collect exempt constant ids into.
    """
    for stmt in tree.body:
        targets: list[str] = []
        if isinstance(stmt, ast.Assign):
            targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            targets = [stmt.target.id]
        value = getattr(stmt, "value", None)
        if not value or not targets:
            continue
        if all(n == n.upper() and n != n.lower() for n in targets):
            for child in ast.walk(value):
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    exempt.add(id(child))


def _exempt_annotation_strings(tree: ast.Module, exempt: set[int]) -> None:
    """Mark strings inside type annotations as exempt.

    Args:
        tree: Parsed AST module.
        exempt: Set to collect exempt constant ids into.
    """
    for node in ast.walk(tree):
        annotation_nodes: list[ast.expr] = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns:
                annotation_nodes.append(node.returns)
            for arg in node.args.args + node.args.kwonlyargs:
                if arg.annotation:
                    annotation_nodes.append(arg.annotation)
        elif isinstance(node, ast.AnnAssign) and node.annotation:
            annotation_nodes.append(node.annotation)
        for ann in annotation_nodes:
            for child in ast.walk(ann):
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    exempt.add(id(child))


def _exempt_decorator_strings(tree: ast.Module, exempt: set[int]) -> None:
    """Mark strings passed as arguments to decorators as exempt.

    Args:
        tree: Parsed AST module.
        exempt: Set to collect exempt constant ids into.
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for decorator in node.decorator_list:
            for child in ast.walk(decorator):
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    exempt.add(id(child))


def _exempt_fstring_fragments(tree: ast.Module, exempt: set[int]) -> None:
    """Mark string fragments inside f-strings as exempt.

    Args:
        tree: Parsed AST module.
        exempt: Set to collect exempt constant ids into.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        for child in node.values:
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                exempt.add(id(child))


def _exempt_dict_keys(tree: ast.Module, exempt: set[int]) -> None:
    """Mark strings used as keys in dict literals as exempt.

    Args:
        tree: Parsed AST module.
        exempt: Set to collect exempt constant ids into.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                exempt.add(id(key))


def _collect_exempt_string_ids(tree: ast.Module) -> set[int]:
    """Collect id() values of string constants in exempt AST contexts.

    Args:
        tree: Parsed AST module.

    Returns:
        Set of id() values for Constant nodes that should not be counted.
    """
    exempt: set[int] = set()
    _exempt_docstring_strings(tree, exempt)
    _exempt_upper_case_strings(tree, exempt)
    _exempt_annotation_strings(tree, exempt)
    _exempt_decorator_strings(tree, exempt)
    _exempt_dict_keys(tree, exempt)
    _exempt_fstring_fragments(tree, exempt)
    return exempt


def _find_repeated_strings(source_code: str, threshold: int) -> list[tuple[str, int]]:
    """Find string literals repeated at or above the threshold in source code.

    Args:
        source_code: Python source code to analyze.
        threshold: Minimum repeat count to flag.

    Returns:
        List of (string_value, count) tuples, sorted by count descending.
    """
    tree = ast.parse(source_code)
    exempt_ids = _collect_exempt_string_ids(tree)
    counts: Counter[str] = Counter()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        if not isinstance(node.value, str):
            continue
        if len(node.value) <= 1:
            continue
        if id(node) in exempt_ids:
            continue
        counts[node.value] += 1
    return sorted(
        [(val, cnt) for val, cnt in counts.items() if cnt >= threshold],
        key=lambda t: t[1],
        reverse=True,
    )
