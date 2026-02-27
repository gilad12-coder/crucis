"""Evaluation-phase orchestration for the Crucis training loop.

This module implements the implementation/evaluation retry cycle: running
implementation agents, checking constraints, running test suites (including
holdout evaluations), and formatting failure feedback.

Extracted from loop.py to keep module size manageable.
"""

import logging
import subprocess
import sys
import threading
import time
from pathlib import Path
from subprocess import Popen

from crucis.cli.runner import (
    build_implementation_command,
    extract_concise_error,
    is_non_transient_error,
    is_rate_limited,
)
from crucis.config import Config
from crucis.constraints.checker import check_constraints
from crucis.constraints.loader import extract_custom_checks, resolve_constraints
from crucis.core._shared import (
    _collect_existing_test_paths,
    _enqueue_optimizer_job,
    _open_run_logger,
    _run_preflight,
)
from crucis.core.curriculum import build_curriculum, write_curriculum_to_workspace
from crucis.core.prompts import build_evaluation_prompt
from crucis.core.verification import (
    collect_holdout_eval_specs,
    objective_for_task,
    redacted_holdout_failure_feedback,
    run_holdout_eval_checks,
    run_pytest_targets,
    validated_unit_name,
    write_generated_tests,
)
from crucis.defaults import LOG_EXCERPT_MAX_CHARS, TEXT_ENCODING, bounded_excerpt
from crucis.display import (
    display_agent_boundary,
    display_error,
    display_evaluation_attempt,
    display_evaluation_result,
    display_sandbox_status,
    display_spinner_context,
    display_test_failure_output,
    display_warning,
)
from crucis.execution.sandbox import check_docker_available
from crucis.models import (
    CheckpointState,
    ParsedObjective,
    TaskConstraints,
    TrainingStatus,
    VerificationGranularity,
)
from crucis.persistence.checkpoint import save_checkpoint
from crucis.persistence.events import EventLogger
from crucis.persistence.policy import OptimizerPolicy

_log = logging.getLogger(__name__)

_PHASE_EVALUATE = "evaluate"
_THREAD_JOIN_TIMEOUT_SEC = 5
_SCOPE_TESTS = "tests"


# Auto-evaluate after fit


def _maybe_auto_evaluate_after_fit(
    auto_evaluate: bool,
    state: CheckpointState,
    config: Config,
    workspace: Path,
    objective: ParsedObjective,
    profiles: dict,
    policy: OptimizerPolicy | None,
    profiles_path: Path,
    checkpoint_path: Path,
    no_sandbox: bool = False,
) -> None:
    """Run optional post-fit evaluation flow.

    Args:
        auto_evaluate: Whether to auto-run evaluation after fit.
        state: Checkpoint state being processed.
        config: Runtime configuration values.
        workspace: Workspace root directory.
        objective: Parsed objective data for the current run.
        profiles: Loaded constraints profile mapping.
        policy: Active optimizer policy used for prompt steering.
        profiles_path: Resolved profiles path used for this run.
        checkpoint_path: Path to the checkpoint file for persisting results.
        no_sandbox: When True, skip Docker sandbox and run pytest on host.
    """
    if not auto_evaluate:
        return

    use_sandbox = False if no_sandbox else check_docker_available()
    display_sandbox_status(use_sandbox)
    constraints_map = {
        progress.name: resolve_constraints(objective, profiles, progress.name, scope=_SCOPE_TESTS)
        for progress in state.task_progress
    }
    implementation_constraints_map = {
        progress.name: resolve_constraints(
            objective, profiles, progress.name, scope="implementation"
        )
        for progress in state.task_progress
    }
    impl_custom_checks_map = {
        progress.name: cc
        for progress in state.task_progress
        if (
            cc := extract_custom_checks(objective, profiles, progress.name, scope="implementation")
        )
    }
    passed = run_evaluation(
        state,
        config,
        test_dir=workspace / "tests",
        objective=objective,
        constraints_map=constraints_map,
        implementation_constraints_map=implementation_constraints_map,
        use_sandbox=use_sandbox,
        policy=policy,
        profiles_path=profiles_path,
        custom_checks_map=impl_custom_checks_map or None,
    )
    if passed:
        state.evaluation_passed = True
        save_checkpoint(state, checkpoint_path)


# Main evaluation entry point


def run_evaluation(
    state: CheckpointState,
    config: Config,
    test_dir: Path = Path("tests"),
    objective: ParsedObjective | None = None,
    constraints_map: dict[str, TaskConstraints] | None = None,
    implementation_constraints_map: dict[str, TaskConstraints] | None = None,
    use_sandbox: bool = False,
    policy: OptimizerPolicy | None = None,
    profiles_path: Path | None = None,
    custom_checks_map: dict[str, dict] | None = None,
    agent_timeout: int | None = None,
) -> bool:
    """Run evaluation-agent generation with retries and optional sandboxed pytest.

    Args:
        state: Checkpoint state being processed.
        config: Runtime configuration values.
        test_dir: Directory containing generated train-suite tests.
        objective: Parsed objective data for the current run.
        constraints_map: Constraints map keyed by task name.
        implementation_constraints_map: Constraints for implementation code.
        use_sandbox: Whether verification runs inside the Docker sandbox.
        policy: Active optimizer policy used for prompt steering.
        profiles_path: Resolved profiles path used for this run.
        custom_checks_map: Optional plugin configs keyed by task name.
        agent_timeout: Override for agent subprocess timeout in seconds.

    Returns:
        True when verification succeeds within retry budget, else False.
    """
    # Assumes test_dir is one level below the workspace root (e.g. <workspace>/tests).
    workspace = test_dir.parent
    _run_preflight(workspace, config, _PHASE_EVALUATE)
    logger = _open_run_logger(workspace, _PHASE_EVALUATE)
    logger.emit(
        "run_started",
        details={
            "workspace": str(workspace),
            "use_sandbox": use_sandbox,
            "has_objective": objective is not None,
        },
    )
    eval_t0 = time.monotonic()
    try:
        test_dir.mkdir(parents=True, exist_ok=True)
        try:
            generated_paths = write_generated_tests(state, test_dir)
        except ValueError as exc:
            display_error(str(exc))
            logger.emit("run_failed", success=False, message=str(exc))
            return False

        curriculum_path = _build_curriculum_for_evaluation(
            state=state,
            objective=objective,
            constraints_map=constraints_map,
            implementation_constraints_map=implementation_constraints_map,
            workspace=workspace,
        )
        max_attempts = max(config.max_iterations, 1)
        passed, success_attempt = _run_evaluation_attempts(
            state=state,
            config=config,
            test_dir=test_dir,
            objective=objective,
            implementation_constraints_map=implementation_constraints_map,
            use_sandbox=use_sandbox,
            policy=policy,
            generated_paths=generated_paths,
            curriculum_path=curriculum_path,
            logger=logger,
            custom_checks_map=custom_checks_map,
            agent_timeout=agent_timeout,
        )
        _enqueue_evaluation_optimizer_job(
            workspace=workspace,
            objective=objective,
            state=state,
            profiles_path=profiles_path,
        )
        _display_and_log_result(passed, success_attempt, max_attempts, state, eval_t0, logger)
        return passed
    finally:
        logger.close()


def _display_and_log_result(
    passed: bool,
    success_attempt: int,
    max_attempts: int,
    state: CheckpointState,
    eval_t0: float,
    logger: EventLogger,
) -> None:
    """Display evaluation result summary and log completion event.

    Args:
        passed: Whether all evaluation gates passed.
        success_attempt: 1-based attempt that succeeded (0 if all failed).
        max_attempts: Maximum allowed attempt count.
        state: Checkpoint state being processed.
        eval_t0: Monotonic start time for elapsed calculation.
        logger: Run event logger.
    """
    complete_tasks = (
        sum(1 for p in state.task_progress if p.status == TrainingStatus.complete)
        if passed
        else None
    )
    total_tasks = len(state.task_progress) if passed else None
    display_evaluation_result(
        passed,
        attempt=success_attempt if passed else None,
        max_attempts=max_attempts if passed else None,
        complete_tasks=complete_tasks,
        total_tasks=total_tasks,
        elapsed_sec=time.monotonic() - eval_t0,
    )
    logger.emit("run_completed", success=passed)


# Evaluation attempt loop


def _run_evaluation_attempts(
    state: CheckpointState,
    config: Config,
    test_dir: Path,
    objective: ParsedObjective | None,
    implementation_constraints_map: dict[str, TaskConstraints] | None,
    use_sandbox: bool,
    policy: OptimizerPolicy | None,
    generated_paths: list[Path],
    curriculum_path: Path | None,
    logger: EventLogger,
    custom_checks_map: dict[str, dict] | None = None,
    agent_timeout: int | None = None,
) -> tuple[bool, int]:
    """Execute implementation/evaluation retry attempts.

    Args:
        state: Checkpoint state being processed.
        config: Runtime configuration values.
        test_dir: Directory containing generated train-suite tests.
        objective: Parsed objective data for the current run.
        implementation_constraints_map: Constraints for implementation code, keyed by task name.
        use_sandbox: Whether verification runs inside the Docker sandbox.
        policy: Active optimizer policy used for prompt steering.
        generated_paths: Written train-suite test file paths.
        curriculum_path: Optional curriculum artifact path.
        logger: Run event logger.
        custom_checks_map: Optional plugin configs keyed by task name.
        agent_timeout: Override for agent subprocess timeout in seconds.

    Returns:
        Tuple of (passed, attempt). attempt is the 1-based attempt number
        that succeeded, or 0 if all attempts failed.
    """
    max_attempts = max(config.max_iterations, 1)
    error_feedback = ""
    for attempt in range(1, max_attempts + 1):
        logger.emit("attempt_started", attempt=attempt, max_attempts=max_attempts)
        display_evaluation_attempt(attempt, max_attempts)
        prompt = build_evaluation_prompt(
            generated_paths,
            curriculum_path,
            error_feedback,
            policy=policy,
        )
        command = build_implementation_command(
            prompt,
            config.implementation_agent,
            config.implementation_model,
        )
        timeout_kwargs = {"timeout": agent_timeout} if agent_timeout is not None else {}
        command_ok, error_feedback = _run_implementation_attempt(command, **timeout_kwargs)
        if not command_ok:
            _log_attempt_failed(
                logger, attempt, max_attempts, "implementation agent failed", error_feedback
            )
            display_error(extract_concise_error(error_feedback))
            if _is_non_retryable_feedback(error_feedback):
                break
            continue

        ok, error_feedback = _run_evaluation_gates(
            state=state,
            objective=objective,
            test_dir=test_dir,
            use_sandbox=use_sandbox,
            implementation_constraints_map=implementation_constraints_map,
            custom_checks_map=custom_checks_map,
            logger=logger,
            attempt=attempt,
            max_attempts=max_attempts,
        )
        if ok:
            return True, attempt
    return False, 0


# Evaluation gates


def _run_evaluation_gates(
    *,
    state: CheckpointState,
    objective: ParsedObjective | None,
    test_dir: Path,
    use_sandbox: bool,
    implementation_constraints_map: dict[str, TaskConstraints] | None,
    custom_checks_map: dict[str, dict] | None,
    logger: EventLogger,
    attempt: int,
    max_attempts: int,
) -> tuple[bool, str]:
    """Run constraint, regression, and verification gates for one attempt.

    Args:
        state: Checkpoint state being processed.
        objective: Parsed objective data for the current run.
        test_dir: Directory containing generated train-suite tests.
        use_sandbox: Whether verification runs inside the Docker sandbox.
        implementation_constraints_map: Constraints keyed by task name.
        custom_checks_map: Optional plugin configs keyed by task name.
        logger: Run event logger.
        attempt: Current 1-based attempt number.
        max_attempts: Maximum attempt count.

    Returns:
        Tuple of (passed, error_feedback).
    """
    if implementation_constraints_map:
        impl_ok, impl_feedback = _check_implementation_constraints(
            workspace=test_dir.parent,
            implementation_constraints_map=implementation_constraints_map,
            custom_checks_map=custom_checks_map,
        )
        if not impl_ok:
            display_test_failure_output(impl_feedback)
            _log_attempt_failed(
                logger, attempt, max_attempts,
                "implementation constraints failed", impl_feedback,
            )
            return False, impl_feedback

    reg_ok, reg_feedback = _run_regression_gate(objective, test_dir, use_sandbox)
    if not reg_ok:
        display_test_failure_output(reg_feedback)
        _log_attempt_failed(
            logger, attempt, max_attempts, "regression gate failed", reg_feedback,
        )
        return False, reg_feedback

    with display_spinner_context("Verifying tests..."):
        passed, verify_feedback = _verify_tests(
            test_dir=test_dir,
            use_sandbox=use_sandbox,
            state=state,
            objective=objective,
        )
    if passed:
        logger.emit(
            "attempt_succeeded", success=True, attempt=attempt,
            max_attempts=max_attempts,
        )
        return True, ""
    display_test_failure_output(verify_feedback)
    _log_attempt_failed(
        logger, attempt, max_attempts, "verification failed", verify_feedback,
    )
    return False, verify_feedback


def _check_implementation_constraints(
    workspace: Path,
    implementation_constraints_map: dict[str, TaskConstraints],
    custom_checks_map: dict[str, dict] | None = None,
) -> tuple[bool, str]:
    """Check implementation source files against resolved constraints.

    Args:
        workspace: Workspace root directory containing implementation files.
        implementation_constraints_map: Implementation constraints keyed by task name.
        custom_checks_map: Optional plugin configs keyed by task name.

    Returns:
        Tuple of (passed, violation_feedback).
    """
    all_violations: list[str] = []
    for task_name, constraints in implementation_constraints_map.items():
        source_parts: list[str] = []
        for target in constraints.target_files:
            target_path = workspace / target
            if target_path.is_file():
                source_parts.append(target_path.read_text(encoding=TEXT_ENCODING))
            else:
                display_warning(f"Target file not found, skipping constraint check: {target}")
        if not source_parts:
            continue
        combined_source = "\n".join(source_parts)
        task_custom = (custom_checks_map or {}).get(task_name)
        primary, secondary = check_constraints(combined_source, constraints, task_custom)
        violations = primary.violations + secondary.violations
        if violations:
            all_violations.append(f"[{task_name}] Implementation constraint violations:")
            all_violations.extend(f"  - {v}" for v in violations)
    if all_violations:
        return False, "\n".join(all_violations)
    return True, ""


def _run_regression_gate(
    objective: ParsedObjective | None,
    test_dir: Path,
    use_sandbox: bool,
) -> tuple[bool, str]:
    """Run existing-test regression gate if applicable.

    Args:
        objective: Parsed objective data for the current run.
        test_dir: Directory containing generated train-suite tests.
        use_sandbox: Whether verification runs inside the Docker sandbox.

    Returns:
        Tuple of (passed, error_feedback).
    """
    if objective is None:
        return True, ""
    existing_test_paths = _collect_existing_test_paths(objective, test_dir.parent)
    if not existing_test_paths:
        return True, ""
    with display_spinner_context("Running existing test regression gate..."):
        reg_passed, reg_output = run_pytest_targets(
            workspace=test_dir.parent,
            targets=existing_test_paths,
            use_sandbox=use_sandbox,
        )
    if not reg_passed:
        return False, f"REGRESSION FAILURE: existing tests broke:\n{reg_output}"
    return True, ""


# Verification


def _verify_tests(
    test_dir: Path,
    use_sandbox: bool,
    state: CheckpointState | None = None,
    objective: ParsedObjective | None = None,
    holdout_specs: dict[str, ParsedObjective] | None = None,
) -> tuple[bool, str]:
    """Run verifier checks with task/objective granularity semantics.

    Args:
        test_dir: Directory containing generated train-suite tests.
        use_sandbox: Whether verification runs inside the Docker sandbox.
        state: Checkpoint state being processed.
        objective: Parsed objective data for the current run.
        holdout_specs: Holdout verification specs grouped by task name.

    Returns:
        True when the operation succeeds; otherwise False.
    """
    if objective is not None and state is not None:
        if objective.verification_granularity == VerificationGranularity.task:
            try:
                return _verify_task_granularity(
                    test_dir=test_dir,
                    use_sandbox=use_sandbox,
                    state=state,
                    objective=objective,
                )
            except ValueError as exc:
                return False, str(exc)
        holdout_specs = collect_holdout_eval_specs(state, objective)

    public_passed, public_output = run_pytest_targets(
        workspace=test_dir.parent,
        targets=[test_dir],
        use_sandbox=use_sandbox,
    )
    if not public_passed:
        return False, public_output

    if not holdout_specs:
        return True, ""

    holdout_passed, holdout_output = run_holdout_eval_checks(
        test_dir=test_dir,
        use_sandbox=use_sandbox,
        holdout_specs=holdout_specs,
    )
    if holdout_passed:
        return True, ""
    if holdout_output.startswith("HOLDOUT EVAL CONFIG ERROR:"):
        return False, holdout_output
    return False, redacted_holdout_failure_feedback(holdout_output, holdout_specs)


def _verify_task_granularity(
    test_dir: Path,
    use_sandbox: bool,
    state: CheckpointState,
    objective: ParsedObjective,
) -> tuple[bool, str]:
    """Verify each task unit independently and aggregate into one attempt verdict.

    Args:
        test_dir: Directory containing generated train-suite tests.
        use_sandbox: Whether verification runs inside the Docker sandbox.
        state: Checkpoint state being processed.
        objective: Parsed objective data for the current run.

    Returns:
        True when the operation succeeds; otherwise False.
    """
    workspace = test_dir.parent
    for progress in state.task_progress:
        if not progress.train_suite_source:
            continue

        task_name = progress.name
        safe_task_name = validated_unit_name(
            task_name,
            "EVALUATION CONFIG ERROR",
        )
        public_target = test_dir / f"test_{safe_task_name}.py"
        if not public_target.exists():
            return (
                False,
                f"Verification unit `{task_name}` failed: "
                f"missing test suite file `{public_target}`.",
            )

        public_passed, public_output = run_pytest_targets(
            workspace=workspace,
            targets=[public_target],
            use_sandbox=use_sandbox,
        )
        if not public_passed:
            return (
                False,
                f"Verification unit `{task_name}` failed public "
                f"test-suite checks:\n{public_output}",
            )

        task_objective = objective_for_task(objective, task_name)
        if not task_objective.holdout_evals:
            continue

        holdout_passed, holdout_output = run_holdout_eval_checks(
            test_dir=test_dir,
            use_sandbox=use_sandbox,
            holdout_specs={task_name: task_objective},
        )
        if holdout_passed:
            continue
        if holdout_output.startswith("HOLDOUT EVAL CONFIG ERROR:"):
            return False, holdout_output
        return (
            False,
            redacted_holdout_failure_feedback(
                holdout_output,
                {task_name: task_objective},
                unit_name=task_name,
            ),
        )

    return True, ""


# Implementation agent


_IMPLEMENTATION_TIMEOUT_SEC = 600
"""Default timeout for implementation agent subprocesses (10 minutes)."""


def _drain_and_join(
    proc: Popen,
    timeout: int,
) -> tuple[list[str], list[str], bool]:
    """Drain stdout/stderr in background threads and wait for process exit.

    Args:
        proc: Running subprocess with stdout/stderr pipes.
        timeout: Maximum seconds before the process is killed.

    Returns:
        Tuple of (stdout_lines, stderr_lines, timed_out).
    """
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _drain(stream, sink: list[str], echo) -> None:
        """Read lines from stream, echoing each to echo and appending to sink.

        Args:
            stream: Readable stream to drain.
            sink: List to accumulate the lines read.
            echo: File-like object to write each line to.
        """
        for line in stream:
            echo.write(line)
            sink.append(line)

    stdout_reader = threading.Thread(
        target=_drain, args=(proc.stdout, stdout_lines, sys.stdout), daemon=True,
    )
    stderr_reader = threading.Thread(
        target=_drain, args=(proc.stderr, stderr_lines, sys.stderr), daemon=True,
    )

    display_agent_boundary("agent output")
    stdout_reader.start()
    stderr_reader.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        proc.wait()

    stdout_reader.join(timeout=_THREAD_JOIN_TIMEOUT_SEC)
    if stdout_reader.is_alive():
        _log.warning("stdout reader thread did not finish within timeout; output may be incomplete")
    stderr_reader.join(timeout=_THREAD_JOIN_TIMEOUT_SEC)
    if stderr_reader.is_alive():
        _log.warning("stderr reader thread did not finish within timeout; output may be incomplete")
    display_agent_boundary("end agent output")

    return stdout_lines, stderr_lines, timed_out


def _run_implementation_attempt(
    command: list[str],
    timeout: int = _IMPLEMENTATION_TIMEOUT_SEC,
) -> tuple[bool, str]:
    """Run one implementation-agent command and return retry feedback on failure.

    Both stdout and stderr stream to the terminal in real time and are
    captured for error detection and retry feedback.  Pipe reading happens
    in dedicated threads so the main thread never blocks on a pipe
    iterator -- it simply waits for process exit with a timeout.

    Args:
        command: Fully built implementation-agent command.
        timeout: Maximum seconds before the agent is killed.

    Returns:
        Tuple of success flag and error feedback text.
    """
    from crucis.cli.runner import _clean_agent_env

    try:
        proc = Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_clean_agent_env(),
        )
    except FileNotFoundError as exc:
        return (
            False,
            _format_agent_failure_feedback(
                returncode=-1,
                stdout="",
                stderr=f"Agent binary not found: {exc}",
            ),
        )

    stdout_lines, stderr_lines, timed_out = _drain_and_join(proc, timeout)

    if timed_out:
        return (
            False,
            _format_agent_failure_feedback(
                returncode=-1,
                stdout="".join(stdout_lines),
                stderr=f"Implementation agent timed out after {timeout}s",
            ),
        )

    if proc.returncode != 0:
        return (
            False,
            _format_agent_failure_feedback(
                returncode=proc.returncode,
                stdout="".join(stdout_lines),
                stderr="".join(stderr_lines),
            ),
        )
    return True, ""


# Helpers


def _log_attempt_failed(
    logger: EventLogger, attempt: int, max_attempts: int, message: str, feedback: str
) -> None:
    """Emit a structured attempt_failed event with bounded feedback excerpt.

    Args:
        logger: Run event logger.
        attempt: Current attempt number.
        max_attempts: Maximum number of retry attempts.
        message: Failure reason message.
        feedback: Raw feedback text to excerpt.
    """
    logger.emit(
        "attempt_failed",
        success=False,
        attempt=attempt,
        max_attempts=max_attempts,
        message=message,
        details={"feedback_excerpt": bounded_excerpt(feedback, LOG_EXCERPT_MAX_CHARS)},
    )


def _build_curriculum_for_evaluation(
    state: CheckpointState,
    objective: ParsedObjective | None,
    constraints_map: dict[str, TaskConstraints] | None,
    implementation_constraints_map: dict[str, TaskConstraints] | None,
    workspace: Path,
) -> Path | None:
    """Build curriculum artifact path when objective context is available.

    Args:
        state: Checkpoint state being processed.
        objective: Parsed objective data for the current run.
        constraints_map: Constraints map keyed by task name.
        implementation_constraints_map: Implementation constraints keyed by task name.
        workspace: Workspace root directory.

    Returns:
        Curriculum path when generated; otherwise None.
    """
    if objective is None or constraints_map is None:
        return None

    curriculum_content = build_curriculum(
        state, objective, constraints_map, implementation_constraints_map, workspace=workspace
    )
    return write_curriculum_to_workspace(curriculum_content, workspace)


def _is_non_retryable_feedback(feedback: str) -> bool:
    """Check if implementation failure feedback indicates a non-retryable error.

    Args:
        feedback: Error feedback from a failed implementation attempt.

    Returns:
        True if the error will recur on retry (rate limit, quota, nesting, etc).
    """
    return is_rate_limited(feedback) or is_non_transient_error(feedback)


def _format_agent_failure_feedback(
    returncode: int,
    stdout: str,
    stderr: str,
    max_chars: int = 1200,
) -> str:
    """Format bounded retry feedback for evaluation-agent failures.

    Args:
        returncode: Exit code from the agent process.
        stdout: Process stdout text.
        stderr: Process stderr text.
        max_chars: Maximum characters to keep from each stream.

    Returns:
        Formatted failure feedback string.
    """
    parts = [f"EVALUATION AGENT FAILED (exit code {returncode})."]
    stderr_excerpt = bounded_excerpt(stderr, max_chars)
    stdout_excerpt = bounded_excerpt(stdout, max_chars)
    if stderr_excerpt:
        parts.append(f"stderr:\n{stderr_excerpt}")
    if stdout_excerpt:
        parts.append(f"stdout:\n{stdout_excerpt}")
    parts.append("Fix the failure and retry evaluation.")
    return "\n\n".join(parts)


def _enqueue_evaluation_optimizer_job(
    workspace: Path,
    objective: ParsedObjective | None,
    state: CheckpointState,
    profiles_path: Path | None,
) -> None:
    """Enqueue background optimizer work after evaluation attempts complete.

    Args:
        workspace: Workspace root directory.
        objective: Parsed objective data for the current run.
        state: Checkpoint state being processed.
        profiles_path: Optional path to the profiles file used for this run.
    """
    if objective is None:
        return
    _enqueue_optimizer_job(
        workspace,
        objective,
        state,
        trigger=_PHASE_EVALUATE,
        profiles_path=profiles_path,
    )
