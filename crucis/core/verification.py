"""Shared verification, holdout evaluation, and test-writing utilities.

Functions in this module are used by both the core training loop and the MCP
server. They were extracted from loop.py to create a clean public API and
eliminate underscore-import coupling.
"""

import ast
import os
import re
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

from crucis.constraints.checker import check_constraints
from crucis.core.constants import HOST_PYTEST_TIMEOUT_SEC
from crucis.defaults import TEXT_ENCODING, sanitized_env
from crucis.display import display_warning
from crucis.execution.constants import PYTHONPATH_ENV
from crucis.execution.sandbox import run_pytest_in_docker
from crucis.models import CheckpointState, ParsedObjective, TaskConstraints

_VALID_UNIT_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_FEEDBACK_ITEMS = 5

# Matches ANSI escape sequences (e.g. color codes) that pytest may embed in output.
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")

# Patterns that indicate potentially dangerous code in holdout eval expressions.
# Matches import statements, exec/eval calls, dunder attributes, and dangerous
# module access (os, sys, subprocess, etc.).
_DANGEROUS_EVAL_PATTERN = re.compile(
    r"(?:"
    r"\bimport\b"
    r"|\bexec\s*\("
    r"|\beval\s*\("
    r"|\bcompile\s*\("
    r"|\b__\w+__\b"
    r"|\bos\."
    r"|\bsys\."
    r"|\bsubprocess\b"
    r"|\bopen\s*\("
    r"|\bgetattr\s*\("
    r"|\bsetattr\s*\("
    r"|\bdelattr\s*\("
    r"|\bglobals\s*\("
    r"|\blocals\s*\("
    r"|\bbreakpoint\s*\("
    r")"
)


# Train-suite validation


def validate_train_suite_syntax(train_suite_source: str) -> tuple[bool, str]:
    """Validate generated train-suite Python syntax.

    Args:
        train_suite_source: Generated pytest train-suite source code.

    Returns:
        Tuple of (valid, error_message).
    """
    if not train_suite_source.strip():
        return False, "Empty test source"
    try:
        ast.parse(train_suite_source)
    except SyntaxError as exc:
        return False, f"Syntax error: {exc}"
    return True, ""


def validate_train_suite_constraints(
    train_suite_source: str,
    constraints: TaskConstraints,
    custom_checks: dict | None = None,
) -> tuple[bool, str]:
    """Check generated train suite against resolved constraints.

    Only primary violations block generation. Secondary violations are
    logged as warnings but do not trigger retries.

    Args:
        train_suite_source: Generated pytest train-suite source code.
        constraints: Resolved constraints for the current task or objective.
        custom_checks: Optional plugin check config for primary/secondary gates.

    Returns:
        Tuple of (passed, violation_text). Passed is False only when
        primary constraints fail.
    """
    primary, secondary = check_constraints(train_suite_source, constraints, custom_checks)
    if secondary.violations:
        display_warning(
            f"{len(secondary.violations)} secondary constraint note(s) (non-blocking):\n"
            + "\n".join(secondary.violations)
        )
    if primary.violations:
        return False, "\n".join(primary.violations)
    return True, ""


# Objective helpers


def objective_for_task(objective: ParsedObjective, task_name: str) -> ParsedObjective:
    """Create a task-scoped objective for prompts and adversarial review.

    Args:
        objective: Parsed objective data for the current run.
        task_name: Task name within the objective.

    Returns:
        A ParsedObjective scoped to the given task.
    """
    for task in objective.tasks:
        if task.name == task_name:
            train_evals = task.train_evals or objective.train_evals
            holdout_evals = task.holdout_evals or objective.holdout_evals
            target_files = task.target_files or objective.target_files
            behaviors = task.behaviors or objective.behaviors
            context_files = task.context_files or objective.context_files
            existing_tests = task.existing_tests or objective.existing_tests
            return ParsedObjective(
                name=task.name,
                description=task.description or objective.description,
                train_evals=list(train_evals),
                holdout_evals=list(holdout_evals),
                behaviors=list(behaviors),
                signature=task.signature or objective.signature,
                tests_constraint_profile=task.tests_constraint_profile
                or objective.tests_constraint_profile,
                implementation_constraint_profile=task.implementation_constraint_profile
                or objective.implementation_constraint_profile,
                target_files=list(target_files),
                context_files=list(context_files),
                existing_tests=list(existing_tests),
                tasks=list(objective.tasks),
                verification_granularity=objective.verification_granularity,
            )

    warnings.warn(
        f"Task '{task_name}' not found in objective; using full objective as fallback",
        stacklevel=2,
    )
    return ParsedObjective(
        name=task_name,
        description=objective.description,
        train_evals=list(objective.train_evals),
        holdout_evals=list(objective.holdout_evals),
        behaviors=list(objective.behaviors),
        signature=objective.signature,
        tests_constraint_profile=objective.tests_constraint_profile,
        implementation_constraint_profile=objective.implementation_constraint_profile,
        target_files=list(objective.target_files),
        context_files=list(objective.context_files),
        existing_tests=list(objective.existing_tests),
        tasks=list(objective.tasks),
        verification_granularity=objective.verification_granularity,
    )


# Test file writing


def validated_unit_name(name: str, error_prefix: str) -> str:
    """Validate verifier unit names before using them in generated file paths.

    Args:
        name: Task/unit name from objective or checkpoint.
        error_prefix: Error prefix to keep feedback context-specific.

    Returns:
        Original name when valid.
    """
    if _VALID_UNIT_NAME_RE.fullmatch(name):
        return name
    raise ValueError(
        f"{error_prefix}: invalid task name `{name}`. "
        "Task names must be valid Python identifiers."
    )


def write_generated_tests(state: CheckpointState, test_dir: Path) -> list[Path]:
    """Write approved train suites from checkpoint state to disk.

    Args:
        state: Checkpoint state being processed.
        test_dir: Directory containing generated train-suite tests.

    Returns:
        List of written file paths.
    """
    written_paths = []
    for progress in state.task_progress:
        if not progress.train_suite_source:
            continue
        safe_name = validated_unit_name(
            progress.name,
            "EVALUATION CONFIG ERROR",
        )
        path = test_dir / f"test_{safe_name}.py"
        path.write_text(progress.train_suite_source, encoding=TEXT_ENCODING)
        written_paths.append(path)
    return written_paths


# Holdout evaluation


def collect_holdout_eval_specs(
    state: CheckpointState,
    objective: ParsedObjective | None,
) -> dict[str, ParsedObjective]:
    """Collect task-scoped objectives that include holdout evals.

    Args:
        state: Checkpoint state being processed.
        objective: Parsed objective data for the current run.

    Returns:
        Dict mapping task name to task-scoped objective.
    """
    if objective is None:
        return {}

    holdout_specs = {}
    for progress in state.task_progress:
        if not progress.train_suite_source:
            continue
        task_objective = objective_for_task(objective, progress.name)
        if task_objective.holdout_evals:
            holdout_specs[progress.name] = task_objective
    return holdout_specs


def run_pytest_targets(
    workspace: Path,
    targets: list[Path],
    use_sandbox: bool,
    timeout_sec: int = HOST_PYTEST_TIMEOUT_SEC,
) -> tuple[bool, str]:
    """Run pytest for targets via host or Docker sandbox.

    Args:
        workspace: Workspace root directory.
        targets: Test file paths to run.
        use_sandbox: Whether verification runs inside the Docker sandbox.
        timeout_sec: Timeout in seconds for host pytest.

    Returns:
        Tuple of (passed, output_text).
    """
    if use_sandbox:
        docker_targets = []
        for target in targets:
            if target.is_absolute():
                try:
                    docker_targets.append(str(target.relative_to(workspace)))
                except ValueError:
                    docker_targets.append(str(target))
            else:
                docker_targets.append(str(target))
        result = run_pytest_in_docker(workspace, test_targets=docker_targets)
        return result.passed, result.stdout + result.stderr

    env = sanitized_env()
    workspace_python_path = str(workspace)
    existing_python_path = env.get(PYTHONPATH_ENV, "")
    if existing_python_path:
        env[PYTHONPATH_ENV] = f"{workspace_python_path}{os.pathsep}{existing_python_path}"
    else:
        env[PYTHONPATH_ENV] = workspace_python_path

    try:
        pytest_result = subprocess.run(
            [sys.executable, "-m", "pytest", *(str(target) for target in targets), "-v"],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=workspace,
            env=env,
        )
    except subprocess.TimeoutExpired:
        target_text = ", ".join(str(target) for target in targets)
        return (
            False,
            f"Host pytest timed out after {timeout_sec}s while running: {target_text}",
        )
    return pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr


def run_holdout_eval_checks(
    test_dir: Path,
    use_sandbox: bool,
    holdout_specs: dict[str, ParsedObjective],
) -> tuple[bool, str]:
    """Run holdout assertions from ephemeral test files.

    Args:
        test_dir: Directory containing generated train-suite tests.
        use_sandbox: Whether verification runs inside the Docker sandbox.
        holdout_specs: Holdout verification specs grouped by task name.

    Returns:
        Tuple of (passed, output_text).
    """
    workspace = test_dir.parent
    with tempfile.TemporaryDirectory(dir=workspace, prefix=".crucis_holdout_eval_") as temp_dir:
        holdout_dir = Path(temp_dir)
        try:
            holdout_paths = write_holdout_eval_tests(holdout_dir, holdout_specs)
        except ValueError as exc:
            return False, str(exc)

        if not holdout_paths:
            return True, ""

        return run_pytest_targets(workspace, holdout_paths, use_sandbox)


def write_holdout_eval_tests(
    holdout_dir: Path,
    holdout_specs: dict[str, ParsedObjective],
) -> list[Path]:
    """Write holdout eval tests and return generated file paths.

    Args:
        holdout_dir: Directory for holdout test files.
        holdout_specs: Holdout verification specs grouped by task name.

    Returns:
        List of written holdout test file paths.
    """
    written_paths = []
    for task_name, task_objective in holdout_specs.items():
        safe_task_name = validated_unit_name(
            task_name,
            "HOLDOUT EVAL CONFIG ERROR",
        )
        test_path = holdout_dir / f"test_holdout_{safe_task_name}.py"
        test_path.write_text(
            build_holdout_eval_test_source(task_objective),
            encoding=TEXT_ENCODING,
        )
        written_paths.append(test_path)
    return written_paths


def _validate_eval_expression(value: str, label: str, case_idx: int, task_name: str) -> bool:
    """Reject holdout eval expressions containing dangerous code patterns.

    Checks the expression against a blocklist of patterns that could enable
    code injection (imports, exec, eval, dunder access, etc.).

    Args:
        value: The expression string from objective YAML (input or output).
        label: Human-readable label for error messages ("input" or "output").
        case_idx: Zero-based index of the holdout case for error context.
        task_name: Task name for error context.

    Returns:
        True when the expression is safe; False when a dangerous pattern
        is detected (with a warning emitted).
    """
    if _DANGEROUS_EVAL_PATTERN.search(value):
        display_warning(
            f"Skipping holdout eval case {case_idx} for task '{task_name}': "
            f"{label} contains a disallowed expression pattern"
        )
        return False
    return True


def build_holdout_eval_test_source(objective: ParsedObjective) -> str:
    """Build hidden pytest source for one task objective.

    Args:
        objective: Parsed objective data for the current run.

    Returns:
        Complete pytest source code for holdout evaluation.
    """
    module_candidates = module_candidates_from_targets(objective.target_files)
    if not module_candidates:
        raise ValueError(
            "HOLDOUT EVAL CONFIG ERROR: Could not derive import module candidates "
            f"for task '{objective.name}' from target_files={objective.target_files!r}. "
            "Provide Python source file paths in target_files."
        )

    lines = [
        "import importlib",
        "",
        f"FUNCTION_NAME = {objective.name!r}",
        f"MODULE_CANDIDATES = {module_candidates!r}",
        "",
        "def _load_target():",
        "    for module_name in MODULE_CANDIDATES:",
        "        try:",
        "            module = importlib.import_module(module_name)",
        "        except Exception:",
        "            continue",
        "        if hasattr(module, FUNCTION_NAME):",
        "            return getattr(module, FUNCTION_NAME)",
        "    raise AssertionError('Could not import target function for holdout evals')",
        "",
        "TARGET_FUNC = _load_target()",
        "",
    ]

    generated_count = 0
    for idx, case in enumerate(objective.holdout_evals):
        if not _validate_eval_expression(
            case.input, "input", idx, objective.name
        ):
            continue
        if not _validate_eval_expression(
            case.output, "output", idx, objective.name
        ):
            continue
        assertion = f"assert TARGET_FUNC{case.input} == {case.output}"
        try:
            ast.parse(assertion)
        except SyntaxError:
            display_warning(
                f"Skipping holdout eval case {idx} for task '{objective.name}': "
                f"constructed assertion is not valid Python"
            )
            continue
        lines.append(f"def test_holdout_case_{idx}():")
        lines.append(f"    {assertion}")
        lines.append("")
        generated_count += 1

    if generated_count == 0 and objective.holdout_evals:
        lines.append("def test_holdout_no_valid_cases():")
        lines.append(
            "    raise AssertionError("
            "'All holdout eval cases were invalid or rejected')"
        )
        lines.append("")

    return "\n".join(lines)


def module_candidates_from_targets(target_files: list[str]) -> list[str]:
    """Build import-module candidates from configured target file paths.

    Args:
        target_files: List of target file paths from the objective.

    Returns:
        List of dotted module name candidates.
    """
    candidates: list[str] = []
    for raw_path in target_files:
        path = Path(raw_path)
        if path.suffix != ".py":
            continue

        parts = list(path.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        if not all(p.isidentifier() for p in parts):
            continue

        append_unique(candidates, ".".join(parts))
        append_unique(candidates, parts[-1])
        if len(parts) > 1 and parts[0] in {"src", "app", "lib"}:
            append_unique(candidates, ".".join(parts[1:]))

    return candidates


# Utility functions


def append_unique(items: list[str], value: str) -> None:
    """Append value to list only if truthy and not already present.

    Args:
        items: Target list to append to.
        value: Candidate value to append.
    """
    if value and value not in items:
        items.append(value)


def parse_holdout_case_results(pytest_output: str) -> list[tuple[str, bool]]:
    """Extract per-case pass/fail from pytest output without leaking values.

    Args:
        pytest_output: Raw pytest output text.

    Returns:
        List of (test_name, passed) tuples for holdout cases.
    """
    results: list[tuple[str, bool]] = []
    for line in pytest_output.splitlines():
        if "::test_holdout_case_" not in line:
            continue
        parts = line.split("::")
        name = parts[-1].split(" ")[0].split("[")[0] if len(parts) > 1 else ""
        if not name.startswith("test_holdout_case_"):
            continue
        passed = "PASSED" in line
        results.append((name, passed))
    return results


def redacted_holdout_failure_feedback(
    holdout_output: str,
    holdout_specs: dict[str, ParsedObjective],
    unit_name: str | None = None,
) -> str:
    """Return non-sensitive feedback text for holdout failures.

    Args:
        holdout_output: Pytest output from holdout verification execution.
        holdout_specs: Holdout verification specs grouped by task name.
        unit_name: Optional verification unit name for prefix.

    Returns:
        Redacted failure feedback string.
    """
    case_results = parse_holdout_case_results(holdout_output)
    failed_cases = sum(1 for _, p in case_results if not p)
    total_cases = len(case_results)
    task_count = len(holdout_specs)
    prefix = f"Verification unit `{unit_name}`: " if unit_name else ""
    lines = [
        f"{prefix}{failed_cases}/{total_cases} "
        f"holdout cases failed across {task_count} task(s).",
    ]
    if case_results:
        for name, passed in case_results:
            status = "PASSED" if passed else "FAILED"
            lines.append(f"  {name}: {status}")
    lines.append("Holdout values are hidden. Generalize your implementation.")
    return "\n".join(lines)


def format_adversarial_feedback(report) -> str:
    """Format adversarial findings into generation feedback text.

    Args:
        report: Adversarial report payload for the current task.

    Returns:
        Formatted feedback text.
    """
    parts = []
    if report.correctness_issues:
        parts.append(
            "CORRECTNESS ISSUES (fix these first — test assertions with wrong expected values):"
        )
        items = report.correctness_issues
        parts.extend(f"  - {item}" for item in items[:_MAX_FEEDBACK_ITEMS])
        if len(items) > _MAX_FEEDBACK_ITEMS:
            parts.append(f"  (and {len(items) - _MAX_FEEDBACK_ITEMS} more)")
    if report.generalization_gaps:
        parts.append("Generalization gaps to address:")
        items = report.generalization_gaps
        parts.extend(f"  - {item}" for item in items[:_MAX_FEEDBACK_ITEMS])
        if len(items) > _MAX_FEEDBACK_ITEMS:
            parts.append(f"  (and {len(items) - _MAX_FEEDBACK_ITEMS} more)")
    if report.suggested_probe_tests:
        parts.append("Suggested tests to add:")
        items = report.suggested_probe_tests
        parts.extend(f"  - {item}" for item in items[:_MAX_FEEDBACK_ITEMS])
        if len(items) > _MAX_FEEDBACK_ITEMS:
            parts.append(f"  (and {len(items) - _MAX_FEEDBACK_ITEMS} more)")
    if report.probe_succeeded:
        parts.append("Warning: a cheating probe implementation passed your test suite.")
        parts.append("Add tests with dynamic/random inputs to prevent hardcoding.")
    return "\n".join(parts)
