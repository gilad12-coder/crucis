"""Test generation, validation, and review for the Crucis training loop.

This module implements the generate-validate-review cycle: running generation
agents, validating syntax and constraints, prompting for user/adversarial
review, and the cheating-probe holdout check.

Extracted from loop.py to keep module size manageable.
"""

import ast
import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from crucis.cli.runner import (
    extract_concise_error,
    extract_rate_limit_detail,
    is_non_transient_error,
    is_rate_limited,
    run_cli_agent,
)
from crucis.config import Config
from crucis.core.prompts import build_generation_prompt
from crucis.core.test_generator import extract_python_from_response
from crucis.core.verification import (
    validate_train_suite_constraints,
    validate_train_suite_syntax,
)
from crucis.defaults import TEXT_ENCODING
from crucis.display import (
    display_adversarial_report,
    display_error,
    display_spinner_context,
    display_test_suite_source,
    display_warning,
    prompt_input,
)
from crucis.core.adversary import verify_probe_with_holdout_evals
from crucis.models import ParsedObjective, TaskConstraints
from crucis.persistence.audit import log_agent_call
from crucis.persistence.events import EventLogger
from crucis.persistence.policy import OptimizerPolicy


# Probe resolution


def _resolve_probe_result(
    probe_succeeded: bool,
    probe_code: str,
    task_objective: ParsedObjective,
) -> bool:
    """Check probe against holdout evals and return adjusted success flag.

    Args:
        probe_succeeded: Whether the adversarial probe passed train tests.
        probe_code: Probe implementation source code.
        task_objective: Scoped objective for the current task.

    Returns:
        False if probe also passes holdout evals (not a real cheat).
    """
    if not (probe_succeeded and probe_code and task_objective.holdout_evals):
        return probe_succeeded
    holdout_cases = [
        {"input": case.input, "output": case.output} for case in task_objective.holdout_evals
    ]
    if verify_probe_with_holdout_evals(probe_code, task_objective.name, holdout_cases):
        return False
    return probe_succeeded


# Generation attempt logging


def _log_generation_attempt(
    logger: EventLogger | None,
    task_name: str,
    attempt: int,
    max_attempts: int,
    outcome: str,
    violation_count: int | None = None,
) -> None:
    """Emit a generation_attempt event if a logger is available.

    Args:
        logger: Optional event logger for structured telemetry.
        task_name: Task name within the objective.
        attempt: Current attempt number (1-based).
        max_attempts: Maximum number of retry attempts.
        outcome: Attempt outcome label.
        violation_count: Number of constraint violations, when applicable.
    """
    if logger is None:
        return
    details: dict = {"outcome": outcome}
    if violation_count is not None:
        details["violation_count"] = violation_count
    logger.emit(
        "generation_attempt",
        task=task_name,
        attempt=attempt,
        max_attempts=max_attempts,
        details=details,
    )


def _report_constraint_violations(
    violations: str,
    prev_count: int,
    attempt: int,
    max_attempts: int,
    logger: EventLogger | None,
    task_name: str,
) -> int:
    """Display and log constraint violations, returning updated count.

    Args:
        violations: Joined violation messages from constraint checker.
        prev_count: Violation count from the previous attempt.
        attempt: Current attempt number (1-based).
        max_attempts: Maximum number of retry attempts.
        logger: Optional event logger for structured telemetry.
        task_name: Task name within the objective.

    Returns:
        Current violation count for the next iteration.
    """
    vc = len(violations.strip().splitlines())
    msg = f"Attempt {attempt}/{max_attempts}: {vc} violation(s)"
    if prev_count:
        msg += f" (was {prev_count})"
    display_warning(f"{msg}. Retrying...\n{violations}")
    _log_generation_attempt(
        logger,
        task_name,
        attempt,
        max_attempts,
        "constraint_violation",
        violation_count=vc,
    )
    return vc


# Validation


def _validate_generation_attempt(
    train_suite_source: str,
    constraints: TaskConstraints,
    n: int,
    max_attempts: int,
    logger: EventLogger | None,
    task_name: str,
    prev_violation_count: int,
    constraint_feedback: str,
    custom_checks: dict | None = None,
) -> tuple[bool, str, int]:
    """Validate syntax and constraints for a single generation attempt.

    Args:
        train_suite_source: Generated pytest train-suite source code.
        constraints: Resolved constraints for the current task or objective.
        n: Current attempt number (1-based).
        max_attempts: Maximum number of retry attempts.
        logger: Optional event logger for structured telemetry.
        task_name: Name of the current task.
        prev_violation_count: Number of violations from the prior attempt.
        constraint_feedback: Constraint feedback carried from prior attempt.
        custom_checks: Optional plugin check config for primary/secondary gates.

    Returns:
        Tuple of (passed, updated_constraint_feedback, updated_violation_count).
    """
    syntax_ok, syntax_errors = validate_train_suite_syntax(train_suite_source)
    if not syntax_ok:
        display_warning(f"Attempt {n}/{max_attempts}: syntax errors. Retrying...\n{syntax_errors}")
        _log_generation_attempt(logger, task_name, n, max_attempts, "syntax_error")
        return False, constraint_feedback, prev_violation_count

    constraints_ok, violations = validate_train_suite_constraints(
        train_suite_source,
        constraints,
        custom_checks=custom_checks,
    )
    if not constraints_ok:
        new_count = _report_constraint_violations(
            violations,
            prev_violation_count,
            n,
            max_attempts,
            logger,
            task_name,
        )
        return False, violations, new_count

    return True, "", 0


# Generate and approve loop


def _generate_and_approve(
    task_objective: ParsedObjective,
    constraints: TaskConstraints,
    config: Config,
    max_attempts: int,
    adversary_feedback: str = "",
    auto: bool = False,
    policy: OptimizerPolicy | None = None,
    logger: EventLogger | None = None,
    plan_content: str = "",
    context_files_content: dict[str, str] | None = None,
    custom_checks: dict | None = None,
    agent_timeout: int | None = None,
) -> str:
    """Run generate -> validate -> review loop until train suite is approved.

    Args:
        task_objective: Scoped objective for the current task.
        constraints: Resolved constraints for the current task or objective.
        config: Runtime configuration values.
        max_attempts: Maximum number of retry attempts.
        adversary_feedback: Adversarial feedback from the prior review cycle.
        auto: Whether to auto-approve interactive review steps.
        policy: Active optimizer policy used for prompt steering.
        logger: Optional event logger for structured telemetry.
        plan_content: Optional structured plan to guide generation.
        context_files_content: Existing file contents keyed by relative path.
        custom_checks: Optional plugin check config for primary/secondary gates.
        agent_timeout: Override for agent subprocess timeout in seconds.

    Returns:
        Approved train-suite source code.
    """
    constraint_feedback = ""
    prev_violation_count = 0
    task_name = task_objective.name
    for attempt_idx in range(max_attempts):
        n = attempt_idx + 1
        train_suite_source = generate_tests(
            task_objective,
            constraints,
            config,
            constraint_feedback,
            adversary_feedback,
            policy=policy,
            attempt=n,
            max_attempts=max_attempts,
            plan_content=plan_content,
            context_files_content=context_files_content,
            logger=logger,
            agent_timeout=agent_timeout,
        )
        if not train_suite_source:
            _log_generation_attempt(logger, task_name, n, max_attempts, "no_output")
            continue

        passed, constraint_feedback, prev_violation_count = _validate_generation_attempt(
            train_suite_source,
            constraints,
            n,
            max_attempts,
            logger,
            task_name,
            prev_violation_count,
            constraint_feedback,
            custom_checks=custom_checks,
        )
        if not passed:
            continue

        _log_generation_attempt(logger, task_name, n, max_attempts, "pending_review")
        approved, selected_source = prompt_user_review(train_suite_source, auto=auto)
        if approved:
            return selected_source

    raise RuntimeError(
        f"Exceeded {max_attempts} attempt(s) for test-suite generation"
    )


# Test generation agent


def generate_tests(
    objective: ParsedObjective,
    constraints: TaskConstraints,
    config: Config,
    constraint_feedback: str = "",
    adversary_feedback: str = "",
    policy: OptimizerPolicy | None = None,
    attempt: int = 1,
    max_attempts: int = 1,
    plan_content: str = "",
    context_files_content: dict[str, str] | None = None,
    logger: EventLogger | None = None,
    agent_timeout: int | None = None,
) -> str:
    """Generate pytest train-suite source for a parsed objective.

    Args:
        objective: Parsed objective data for the current run.
        constraints: Resolved constraints for the current task or objective.
        config: Runtime configuration values.
        constraint_feedback: Constraint failure feedback from the prior generation attempt.
        adversary_feedback: Adversarial feedback from the prior review cycle.
        policy: Active optimizer policy used for prompt steering.
        attempt: Current generation attempt number (1-based).
        max_attempts: Maximum number of generation attempts.
        plan_content: Optional structured plan to guide generation.
        context_files_content: Existing file contents keyed by relative path.
        logger: Optional event logger for audit trail.
        agent_timeout: Override for agent subprocess timeout in seconds.

    Returns:
        Computed text result for this operation.
    """
    prompt = build_generation_prompt(
        objective,
        constraints,
        constraint_feedback,
        adversary_feedback,
        policy=policy,
        plan_content=plan_content,
        context_files_content=context_files_content,
    )
    timeout_kwargs = {"timeout": agent_timeout} if agent_timeout is not None else {}
    spinner_msg = f"Generating test suite (attempt {attempt}/{max_attempts})..."
    with display_spinner_context(spinner_msg):
        t0 = time.monotonic()
        result = run_cli_agent(
            prompt,
            config.generation_agent,
            config.generation_model,
            config.max_budget_usd,
            **timeout_kwargs,
        )
        duration = time.monotonic() - t0
    log_agent_call(
        logger,
        prompt=prompt,
        result=result,
        agent=config.generation_agent,
        model=config.generation_model,
        budget=config.max_budget_usd,
        duration_sec=duration,
        call_site="generate_tests",
        task=objective.name,
        attempt=attempt,
        max_attempts=max_attempts,
    )

    if result.exit_code != 0:
        if is_rate_limited(result.stderr):
            detail = extract_rate_limit_detail(result.stderr)
            raise RuntimeError(f"Agent rate-limited by the provider. {detail}")
        concise = extract_concise_error(result.stderr)
        if is_non_transient_error(result.stderr):
            raise RuntimeError(f"Non-transient agent error: {concise}")
        display_error(f"Generation failed: {concise}")
        return ""

    return extract_python_from_response(result.stdout)


# User and adversarial review


def prompt_user_review(train_suite_source: str, auto: bool = False) -> tuple[bool, str]:
    """Prompt user to approve, edit, or regenerate generated train suite.

    Args:
        train_suite_source: Generated pytest train-suite source code.
        auto: Whether to auto-approve interactive review steps.

    Returns:
        True when the operation succeeds; otherwise False.
    """
    display_test_suite_source(train_suite_source)
    if auto or not sys.stdin.isatty():
        return True, train_suite_source

    while True:
        decision = prompt_input(
            "[bold cyan]Review:[/bold cyan] [a]pprove / [e]dit / [r]egenerate: "
        ).lower()
        if decision in {"a", "approve"}:
            return True, train_suite_source
        if decision in {"r", "regenerate"}:
            return False, ""
        if decision in {"e", "edit"}:
            edited = _open_in_editor(train_suite_source)
            if edited is not None:
                try:
                    ast.parse(edited)
                except SyntaxError as exc:
                    display_warning(f"Edited code has syntax errors: {exc}")
                    continue
                train_suite_source = edited
                display_test_suite_source(train_suite_source)
            continue
        display_warning("Enter 'a', 'e', or 'r'.")


def _has_actionable_gaps(report) -> bool:
    """Check whether the adversarial report identifies gaps worth addressing.

    Args:
        report: Adversarial report payload for the current task.

    Returns:
        True if the report contains generalization gaps or suggested probes.
    """
    if getattr(report, "correctness_issues", None):
        return True
    if getattr(report, "probe_succeeded", False):
        return True
    if getattr(report, "generalization_gaps", None):
        return True
    return bool(getattr(report, "suggested_probe_tests", None))


def prompt_adversarial_review(report, auto: bool = False) -> bool:
    """Display adversarial report and prompt user to improve or continue.

    Args:
        report: Adversarial report payload for the current task.
        auto: Whether to auto-approve interactive review steps.

    Returns:
        True to accept tests as-is, False to regenerate with feedback.
    """
    display_adversarial_report(report)
    if auto:
        return not _has_actionable_gaps(report)

    while True:
        decision = prompt_input(
            "[bold magenta]Adversary:[/bold magenta] [i]mprove tests / [d]one: "
        ).lower()
        if decision in {"d", "done"}:
            return True
        if decision in {"i", "improve"}:
            return False
        display_warning("Enter 'i' or 'd'.")


def _open_in_editor(source: str) -> str | None:
    """Open source in $EDITOR and return edited content.

    Args:
        source: Python source code to validate or render.

    Returns:
        Computed text result for this operation.
    """
    editor = os.environ.get("EDITOR", "vi")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".py",
            mode="w",
            encoding=TEXT_ENCODING,
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(source)

        subprocess.run([*shlex.split(editor), str(temp_path)], check=True)
        return temp_path.read_text(encoding=TEXT_ENCODING)
    except (subprocess.CalledProcessError, FileNotFoundError):
        display_error(f"Could not open editor: {editor}")
        return None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
