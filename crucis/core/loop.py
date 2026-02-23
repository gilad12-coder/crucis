"""Main Crucis training loop for generation, adversarial review, and evaluation."""

__all__ = [
    "_append_unique",
    "_bounded_excerpt",
    "_build_curriculum_for_evaluation",
    "_collect_existing_test_paths",
    "_build_holdout_eval_test_source",
    "_check_implementation_constraints",
    "_collect_holdout_eval_specs",
    "_count_failed_cases",
    "_enqueue_evaluation_optimizer_job",
    "_enqueue_optimizer_job",
    "_format_adversarial_feedback",
    "_format_agent_failure_feedback",
    "_generate_and_approve",
    "_load_or_create_checkpoint",
    "_load_policy_or_none",
    "_log_generation_attempt",
    "_maybe_auto_evaluate_after_fit",
    "_module_candidates_from_targets",
    "_objective_for_task",
    "_open_in_editor",
    "_read_task_context_files",
    "_redacted_holdout_failure_feedback",
    "_report_constraint_violations",
    "_resolve_probe_result",
    "_resolve_profiles_path",
    "_run_holdout_eval_checks",
    "_run_implementation_attempt",
    "_run_pytest_targets",
    "_validated_unit_name",
    "_verify_task_granularity",
    "_verify_tests",
    "_write_generated_tests",
    "_write_holdout_eval_tests",
    "generate_tests",
    "process_task",
    "prompt_adversarial_review",
    "prompt_user_review",
    "run_evaluation",
    "run_fit",
    "validate_train_suite_constraints",
    "validate_train_suite_syntax",
]

import ast
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from crucis.cli.runner import (
    build_implementation_command,
    is_non_transient_error,
    is_rate_limited,
    run_cli_agent,
)
from crucis.config import Config
from crucis.constraints.checker import check_constraints
from crucis.constraints.loader import load_profiles, resolve_constraints
from crucis.core.adversary import (
    run_adversarial_probe,
    run_adversarial_review,
    verify_probe_with_holdout_evals,
)
from crucis.core.constants import HOST_PYTEST_TIMEOUT_SEC
from crucis.core.curriculum import build_curriculum, read_context_files, write_curriculum_to_workspace
from crucis.core.planner import load_plan
from crucis.core.prompts import build_evaluation_prompt, build_generation_prompt
from crucis.core.test_generator import extract_python_from_response
from crucis.defaults import LOG_EXCERPT_MAX_CHARS, TEXT_ENCODING
from crucis.display import (
    display_adversarial_report,
    display_dry_run_prompt,
    display_error,
    display_evaluation_attempt,
    display_evaluation_result,
    display_fit_complete,
    display_hardening_cycle,
    display_sandbox_status,
    display_spinner_context,
    display_task_header,
    display_test_failure_output,
    display_train_suite_source,
    display_workspace,
)
from crucis.execution.optimizer import enqueue_background_optimization
from crucis.execution.sandbox import check_docker_available, run_pytest_in_docker
from crucis.intake.objective import parse_objective
from crucis.models import (
    CheckpointState,
    ParsedObjective,
    TaskConstraints,
    TaskProgress,
    TrainingStatus,
    VerificationGranularity,
)
from crucis.persistence.checkpoint import create_checkpoint, load_checkpoint, save_checkpoint
from crucis.persistence.events import EventLogger
from crucis.persistence.policy import OptimizerPolicy, load_active_policy

_PYTHONPATH_ENV = "PYTHONPATH"
_SCOPE_TESTS = "tests"
_VALID_UNIT_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _read_task_context_files(
    objective: ParsedObjective,
    workspace: Path | None,
) -> dict[str, str]:
    """Read context files from objective and all tasks.

    Args:
        objective: Parsed objective data for the current run.
        workspace: Workspace root directory.

    Returns:
        Dict mapping relative path to file contents, empty when workspace is None.
    """
    if workspace is None:
        return {}
    all_paths = list(objective.context_files)
    for task in objective.tasks:
        all_paths.extend(task.context_files)
    if not all_paths:
        return {}
    return read_context_files(workspace, all_paths)


def _collect_existing_test_paths(
    objective: ParsedObjective,
    workspace: Path,
) -> list[Path]:
    """Collect existing_tests from objective and tasks, filter to files that exist.

    Args:
        objective: Parsed objective data for the current run.
        workspace: Workspace root directory.

    Returns:
        Absolute paths to existing test files on disk.
    """
    all_rel: list[str] = list(objective.existing_tests)
    for task in objective.tasks:
        all_rel.extend(task.existing_tests)
    seen: set[str] = set()
    result: list[Path] = []
    for rel in all_rel:
        if rel in seen:
            continue
        seen.add(rel)
        full = workspace / rel
        if full.is_file():
            result.append(full)
    return result


def _load_fit_context(
    objective_path: Path, profiles_path: Path, workspace: Path | None
) -> tuple[ParsedObjective, Path, Path, dict, OptimizerPolicy | None, str]:
    """Parse objective, load profiles, policy, and plan for a fit session.

    Args:
        objective_path: Path to objective YAML file.
        profiles_path: Path to constraint profiles YAML.
        workspace: Optional workspace root override.

    Returns:
        Tuple of (objective, workspace, profiles_path, profiles, policy, plan_content).
    """
    objective = parse_objective(objective_path)
    workspace = workspace or objective_path.parent
    prof_path = _resolve_profiles_path(workspace, profiles_path)
    profiles = load_profiles(prof_path)
    policy = _load_policy_or_none(workspace)
    plan_content = load_plan(workspace) or ""
    return objective, workspace, prof_path, profiles, policy, plan_content


def run_fit(
    objective_path: Path,
    profiles_path: Path,
    checkpoint_path: Path,
    auto_tests: bool = False,
    auto_adversary: bool = False,
    auto_evaluate: bool = False,
    workspace: Path | None = None,
    dry_run: bool = False,
    task_names: list[str] | None = None,
) -> CheckpointState:
    """Run or resume a Crucis fit session for all unfinished tasks.

    Args:
    Parameters are described below.

    Returns:
        Updated checkpoint state.
    """
    objective, workspace, prof_path, profiles, active_policy, plan_content = _load_fit_context(
        objective_path,
        profiles_path,
        workspace,
    )
    _validate_task_names(objective, task_names)

    if dry_run:
        _display_dry_run(objective, profiles, active_policy, plan_content, task_names, workspace)
        return CheckpointState(task_progress=[])

    checkpoint_path, state = _load_or_create_checkpoint(workspace, checkpoint_path, objective)
    logger = _open_run_logger(workspace, "fit")
    _emit_fit_run_started(
        logger=logger,
        objective_path=objective_path,
        checkpoint_path=checkpoint_path,
        auto_tests=auto_tests,
        auto_adversary=auto_adversary,
        auto_evaluate=auto_evaluate,
    )
    try:
        _run_fit_tasks(
            state=state,
            workspace=workspace,
            objective=objective,
            profiles=profiles,
            config=Config(),
            checkpoint_path=checkpoint_path,
            auto_tests=auto_tests,
            auto_adversary=auto_adversary,
            objective_path=objective_path,
            policy=active_policy,
            logger=logger,
            plan_content=plan_content,
            task_names=task_names,
        )
        _enqueue_optimizer_job(
            workspace,
            objective,
            state,
            trigger="fit",
            profiles_path=prof_path,
        )
        _maybe_auto_evaluate_after_fit(
            auto_evaluate=auto_evaluate,
            state=state,
            config=Config(),
            workspace=workspace,
            objective=objective,
            profiles=profiles,
            policy=active_policy,
            profiles_path=prof_path,
        )
        _emit_fit_run_completed(logger, state)
        return state
    except Exception as exc:
        logger.emit("run_failed", success=False, message=str(exc))
        raise
    finally:
        logger.close()


def _load_or_create_checkpoint(
    workspace: Path, checkpoint_path: Path, objective: ParsedObjective
) -> tuple[Path, CheckpointState]:
    """Resolve checkpoint path and load or create initial state.

    Args:
        workspace: Workspace root directory.
        checkpoint_path: Path to checkpoint file.
        objective: Parsed objective data for the current run.

    Returns:
        Resolved checkpoint path and loaded state.
    """
    if not checkpoint_path.is_absolute():
        checkpoint_path = workspace / checkpoint_path
    state = load_checkpoint(checkpoint_path)
    if state is None:
        state = create_checkpoint(objective)
        save_checkpoint(state, checkpoint_path)
    return checkpoint_path, state


def _validate_task_names(objective: ParsedObjective, task_names: list[str] | None) -> None:
    """Check that all requested task names exist in the objective.

    Args:
        objective: Parsed objective data for the current run.
        task_names: Optional list of task names to validate.
    """
    if not task_names:
        return
    known = {task.name for task in objective.tasks}
    if not objective.tasks:
        known.add(objective.name)
    unknown = set(task_names) - known
    if unknown:
        sep = ", "
        raise ValueError(
            f"Unknown task(s): {sep.join(sorted(unknown))}. Known: {sep.join(sorted(known))}"
        )


def _display_dry_run(
    objective: ParsedObjective,
    profiles: dict,
    policy: OptimizerPolicy | None,
    plan_content: str,
    task_names: list[str] | None = None,
    workspace: Path | None = None,
) -> None:
    """Build and display generation prompts for selected tasks.

    Args:
        objective: Parsed objective data for the current run.
        profiles: Loaded constraint profiles.
        policy: Active optimizer policy used for prompt steering.
        plan_content: Optional structured plan to guide generation.
        task_names: Optional list of task names to display; None means all.
        workspace: Workspace root for reading context files.
    """
    from crucis.config import Config

    config = Config()
    context_files_content = _read_task_context_files(objective, workspace)
    filter_set = set(task_names) if task_names else None
    tasks = objective.tasks or [objective]
    print(f"Objective: {objective.name} ({len(tasks)} task(s))")
    if workspace:
        print(f"Workspace: {workspace}")
    print(f"Agent: {config.generation_agent} / {config.generation_model or 'default'}")
    shown = 0
    for task in tasks:
        if filter_set and task.name not in filter_set:
            continue
        task_objective = _objective_for_task(objective, task.name)
        constraints = resolve_constraints(objective, profiles, task.name)
        prompt = build_generation_prompt(
            task_objective,
            constraints,
            policy=policy,
            plan_content=plan_content,
            context_files_content=context_files_content,
        )
        display_dry_run_prompt(task.name, prompt)
        shown += 1
    if objective.existing_tests:
        print(f"\nRegression gate: {len(objective.existing_tests)} existing test file(s) configured.")
    if objective.context_files:
        print(f"Context files: {len(objective.context_files)} file(s) will be injected into prompts.")
    print(f"\nDry run complete ({shown} task(s)). No agents were invoked.")


def _emit_fit_run_started(
    logger: EventLogger,
    objective_path: Path,
    checkpoint_path: Path,
    auto_tests: bool,
    auto_adversary: bool,
    auto_evaluate: bool,
) -> None:
    """Emit fit run start telemetry event.

    Args:
        logger: Run event logger.
        objective_path: Path to objective YAML file.
        checkpoint_path: Path to checkpoint file.
        auto_tests: Whether to auto-approve generated train suites.
        auto_adversary: Whether to auto-accept adversarial review.
        auto_evaluate: Whether to auto-run evaluation after fit.
    """
    logger.emit(
        "run_started",
        details={
            "objective_path": str(objective_path),
            "checkpoint_path": str(checkpoint_path),
            "auto_tests": auto_tests,
            "auto_adversary": auto_adversary,
            "auto_evaluate": auto_evaluate,
        },
    )


def _emit_fit_run_completed(logger: EventLogger, state: CheckpointState) -> None:
    """Emit fit run completion telemetry event.

    Args:
        logger: Run event logger.
        state: Checkpoint state being processed.
    """
    logger.emit(
        "run_completed",
        success=True,
        details={
            "total_tasks": len(state.task_progress),
            "complete_tasks": sum(
                1 for progress in state.task_progress if progress.status == TrainingStatus.complete
            ),
        },
    )


def _open_run_logger(workspace: Path, phase: str) -> EventLogger:
    """Create and announce a run logger.

    Args:
        workspace: Workspace root directory.
        phase: Event phase name.

    Returns:
        Created logger instance.
    """
    logger = EventLogger(workspace, phase)
    if logger.path is not None:
        print(f"Run log: {logger.path}")
    return logger


def _run_fit_tasks(
    state: CheckpointState,
    workspace: Path,
    objective: ParsedObjective,
    profiles: dict,
    config: Config,
    checkpoint_path: Path,
    auto_tests: bool,
    auto_adversary: bool,
    objective_path: Path,
    policy: OptimizerPolicy | None,
    logger: EventLogger,
    plan_content: str = "",
    task_names: list[str] | None = None,
) -> None:
    """Process all unfinished fit tasks and persist progress.

    Args:
        state: Checkpoint state being processed.
        workspace: Workspace root directory.
        objective: Parsed objective data for the current run.
        profiles: Loaded constraints profile mapping.
        config: Runtime configuration values.
        checkpoint_path: Path to checkpoint file.
        auto_tests: Whether to auto-approve generated train suites.
        auto_adversary: Whether to auto-accept adversarial review.
        objective_path: Path to objective YAML file.
        policy: Active optimizer policy used for prompt steering.
        logger: Run event logger.
        plan_content: Optional structured plan to guide generation.
        task_names: Optional list of task names to process; None means all.
    """
    display_workspace(workspace)
    filter_set = set(task_names) if task_names else None
    total = len(state.task_progress)
    for index, progress in enumerate(state.task_progress):
        if progress.status == TrainingStatus.complete:
            continue
        if filter_set and progress.name not in filter_set:
            continue
        _process_fit_task(
            state=state,
            index=index,
            total=total,
            objective=objective,
            profiles=profiles,
            config=config,
            checkpoint_path=checkpoint_path,
            auto_tests=auto_tests,
            auto_adversary=auto_adversary,
            policy=policy,
            logger=logger,
            plan_content=plan_content,
            workspace=workspace,
        )
    display_fit_complete(state, objective_path=str(objective_path))


def _process_fit_task(
    state: CheckpointState,
    index: int,
    total: int,
    objective: ParsedObjective,
    profiles: dict,
    config: Config,
    checkpoint_path: Path,
    auto_tests: bool,
    auto_adversary: bool,
    policy: OptimizerPolicy | None,
    logger: EventLogger,
    plan_content: str = "",
    workspace: Path | None = None,
) -> None:
    """Run one fit task iteration and persist the checkpoint.

    Args:
        state: Checkpoint state being processed.
        index: Task index in checkpoint progress list.
        total: Total number of task entries.
        objective: Parsed objective data for the current run.
        profiles: Loaded constraints profile mapping.
        config: Runtime configuration values.
        checkpoint_path: Path to checkpoint file.
        auto_tests: Whether to auto-approve generated train suites.
        auto_adversary: Whether to auto-accept adversarial review.
        policy: Active optimizer policy used for prompt steering.
        logger: Run event logger.
        plan_content: Optional structured plan to guide generation.
        workspace: Workspace root for reading context files.
    """
    progress = state.task_progress[index]
    logger.emit("task_started", task=progress.name, attempt=index + 1, max_attempts=total)
    constraints = resolve_constraints(objective, profiles, progress.name)
    display_task_header(progress.name, index=index + 1, total=total)
    try:
        updated = process_task(
            progress.name,
            objective,
            constraints,
            config,
            auto_tests=auto_tests,
            auto_adversary=auto_adversary,
            policy=policy,
            logger=logger,
            plan_content=plan_content,
            workspace=workspace,
        )
    except Exception as exc:
        logger.emit("task_failed", task=progress.name, success=False, message=str(exc))
        raise

    state.task_progress[index] = updated
    save_checkpoint(state, checkpoint_path)
    logger.emit(
        "task_completed",
        task=progress.name,
        success=True,
        details={"status": updated.status.value},
    )


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


def process_task(
    task_name: str,
    objective: ParsedObjective,
    constraints: TaskConstraints,
    config: Config,
    auto_tests: bool = False,
    auto_adversary: bool = False,
    policy: OptimizerPolicy | None = None,
    logger: EventLogger | None = None,
    plan_content: str = "",
    workspace: Path | None = None,
) -> TaskProgress:
    """Generate and review train suites for one task, then adversarially probe.

    Args:
        task_name: Task name within the objective.
        objective: Parsed objective data for the current run.
        constraints: Resolved constraints for the current task or objective.
        config: Runtime configuration values.
        auto_tests: Whether to auto-approve generated train suites.
        auto_adversary: Whether to auto-accept adversarial review.
        policy: Active optimizer policy used for prompt steering.
        logger: Optional event logger for structured telemetry.
        plan_content: Optional structured plan to guide generation.
        workspace: Workspace root for reading context files.

    Returns:
        Task progress for the processed task.
    """
    task_objective = _objective_for_task(objective, task_name)
    context_files_content = _read_task_context_files(objective, workspace)
    max_attempts = max(config.max_iterations, 1)

    max_adversary_cycles = 2 if auto_adversary else max_attempts
    adversary_feedback = ""
    for cycle_idx in range(max_adversary_cycles):
        display_hardening_cycle(task_name, cycle_idx + 1, max_adversary_cycles)
        approved_source = _generate_and_approve(
            task_objective,
            constraints,
            config,
            max_attempts,
            adversary_feedback,
            auto=auto_tests,
            policy=policy,
            logger=logger,
            plan_content=plan_content,
            context_files_content=context_files_content,
        )
        with display_spinner_context("Running adversarial review..."):
            report = run_adversarial_review(
                approved_source, task_objective, config,
                constraints=constraints, policy=policy,
            )
        with display_spinner_context("Running adversarial probe..."):
            probe_succeeded, probe_code = run_adversarial_probe(
                approved_source, task_objective, config, policy=policy,
            )
        probe_succeeded = _resolve_probe_result(probe_succeeded, probe_code, task_objective)
        report.probe_succeeded = probe_succeeded
        report.probe_code = probe_code

        if logger:
            logger.emit(
                "adversarial_completed",
                task=task_name,
                details={"probe_succeeded": probe_succeeded},
            )

        if prompt_adversarial_review(report, auto=auto_adversary):
            break
        adversary_feedback = _format_adversarial_feedback(report)

    return TaskProgress(
        name=task_name,
        status=TrainingStatus.complete,
        train_suite_source=approved_source,
        adversarial_report=report,
    )


def _maybe_auto_evaluate_after_fit(
    auto_evaluate: bool,
    state: CheckpointState,
    config: Config,
    workspace: Path,
    objective: ParsedObjective,
    profiles: dict,
    policy: OptimizerPolicy | None,
    profiles_path: Path,
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
    """
    if not auto_evaluate:
        return

    use_sandbox = check_docker_available()
    display_sandbox_status(use_sandbox)
    constraints_map = {
        progress.name: resolve_constraints(objective, profiles, progress.name, scope=_SCOPE_TESTS)
        for progress in state.task_progress
    }
    implementation_constraints_map = {
        progress.name: resolve_constraints(objective, profiles, progress.name, scope="implementation")
        for progress in state.task_progress
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
    )
    display_evaluation_result(passed)


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
    display_error(f"{msg}. Retrying...\n{violations}")
    _log_generation_attempt(
        logger,
        task_name,
        attempt,
        max_attempts,
        "constraint_violation",
        violation_count=vc,
    )
    return vc


def _validate_generation_attempt(
    train_suite_source: str,
    constraints: TaskConstraints,
    n: int,
    max_attempts: int,
    logger: EventLogger | None,
    task_name: str,
    prev_violation_count: int,
    constraint_feedback: str,
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

    Returns:
        Tuple of (passed, updated_constraint_feedback, updated_violation_count).
    """
    syntax_ok, syntax_errors = validate_train_suite_syntax(train_suite_source)
    if not syntax_ok:
        display_error(f"Attempt {n}/{max_attempts}: syntax errors. Retrying...\n{syntax_errors}")
        _log_generation_attempt(logger, task_name, n, max_attempts, "syntax_error")
        return False, constraint_feedback, prev_violation_count

    constraints_ok, violations = validate_train_suite_constraints(
        train_suite_source,
        constraints,
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
        )
        if not train_suite_source:
            display_error(f"Attempt {n}/{max_attempts}: agent returned no output. Retrying...")
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
        )
        if not passed:
            continue

        _log_generation_attempt(logger, task_name, n, max_attempts, "approved")
        approved, selected_source = prompt_user_review(train_suite_source, auto=auto)
        if approved:
            return selected_source

    raise RuntimeError(
        f"Exceeded max_iterations={config.max_iterations} for train-suite generation"
    )


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
    spinner_msg = f"Generating train suite (attempt {attempt}/{max_attempts})..."
    with display_spinner_context(spinner_msg):
        result = run_cli_agent(
            prompt,
            config.generation_agent,
            config.generation_model,
            config.max_budget_usd,
        )

    if result.exit_code != 0:
        if is_rate_limited(result.stderr):
            raise RuntimeError("Agent rate-limited by the provider.")
        if is_non_transient_error(result.stderr):
            raise RuntimeError(f"Non-transient agent error: {result.stderr.strip()}")
        display_error(f"Generation failed: {result.stderr}")
        return ""

    return extract_python_from_response(result.stdout)


def prompt_user_review(train_suite_source: str, auto: bool = False) -> tuple[bool, str]:
    """Prompt user to approve, edit, or regenerate generated train suite.

    Args:
        train_suite_source: Generated pytest train-suite source code.
        auto: Whether to auto-approve interactive review steps.

    Returns:
        True when the operation succeeds; otherwise False.
    """
    display_train_suite_source(train_suite_source)
    if auto:
        return True, train_suite_source

    while True:
        decision = input("Review: [a]pprove / [e]dit / [r]egenerate: ").strip().lower()
        if decision in {"a", "approve"}:
            return True, train_suite_source
        if decision in {"r", "regenerate"}:
            return False, ""
        if decision in {"e", "edit"}:
            edited = _open_in_editor(train_suite_source)
            if edited is not None:
                train_suite_source = edited
                display_train_suite_source(train_suite_source)
            continue
        print("Enter 'a', 'e', or 'r'.")


def prompt_adversarial_review(report, auto: bool = False) -> bool:
    """Display adversarial report and prompt user to improve or continue.

    Args:
        report: Adversarial report payload for the current task.
        auto: Whether to auto-approve interactive review steps.

    Returns:
        True when the operation succeeds; otherwise False.
    """
    display_adversarial_report(report)
    if auto:
        return not getattr(report, "probe_succeeded", False)

    while True:
        decision = input("Adversary: [i]mprove tests / [d]one: ").strip().lower()
        if decision in {"d", "done"}:
            return True
        if decision in {"i", "improve"}:
            return False
        print("Enter 'i' or 'd'.")


def _open_in_editor(source: str) -> str | None:
    """Open source in $EDITOR and return edited content.

    Args:
        source: Python source code to validate or render.

    Returns:
        Computed text result for this operation.
    """
    editor = os.environ.get("EDITOR", "vi")
    with tempfile.NamedTemporaryFile(
        suffix=".py",
        mode="w",
        encoding=TEXT_ENCODING,
        delete=False,
    ) as temp_file:
        temp_file.write(source)
        temp_path = Path(temp_file.name)

    try:
        subprocess.run([editor, str(temp_path)], check=True)
        return temp_path.read_text(encoding=TEXT_ENCODING)
    except (subprocess.CalledProcessError, FileNotFoundError):
        display_error(f"Could not open editor: {editor}")
        return None
    finally:
        temp_path.unlink(missing_ok=True)


def validate_train_suite_syntax(train_suite_source: str) -> tuple[bool, str]:
    """Validate generated train-suite Python syntax.

    Args:
        train_suite_source: Generated pytest train-suite source code.

    Returns:
        True when the operation succeeds; otherwise False.
    """
    try:
        ast.parse(train_suite_source)
    except SyntaxError as exc:
        return False, f"Syntax error: {exc}"
    if not train_suite_source.strip():
        return False, "Empty test source"
    return True, ""


def validate_train_suite_constraints(
    train_suite_source: str,
    constraints: TaskConstraints,
) -> tuple[bool, str]:
    """Check generated train suite against resolved constraints.

    Args:
        train_suite_source: Generated pytest train-suite source code.
        constraints: Resolved constraints for the current task or objective.

    Returns:
        True when the operation succeeds; otherwise False.
    """
    primary, secondary = check_constraints(train_suite_source, constraints)
    violations = primary.violations + secondary.violations
    if violations:
        return False, "\n".join(violations)
    return True, ""


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
) -> bool:
    """Run evaluation-agent generation with retries and optional sandboxed pytest.

    Args:
    Parameters are described below.

    Returns:
        True when verification succeeds within retry budget, else False.
    """
    workspace = test_dir.parent
    logger = _open_run_logger(workspace, "evaluate")
    logger.emit(
        "run_started",
        details={
            "workspace": str(workspace),
            "use_sandbox": use_sandbox,
            "has_objective": objective is not None,
        },
    )
    try:
        test_dir.mkdir(parents=True, exist_ok=True)
        try:
            generated_paths = _write_generated_tests(state, test_dir)
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
        passed = _run_evaluation_attempts(
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
        )
        _enqueue_evaluation_optimizer_job(
            workspace=workspace,
            objective=objective,
            state=state,
            profiles_path=profiles_path,
        )
        logger.emit("run_completed", success=passed)
        return passed
    finally:
        logger.close()


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
        details={"feedback_excerpt": _bounded_excerpt(feedback, LOG_EXCERPT_MAX_CHARS)},
    )


def _check_implementation_constraints(
    workspace: Path,
    implementation_constraints_map: dict[str, TaskConstraints],
) -> tuple[bool, str]:
    """Check implementation source files against resolved constraints.

    Args:
        workspace: Workspace root directory containing implementation files.
        implementation_constraints_map: Implementation constraints keyed by task name.

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
        if not source_parts:
            continue
        combined_source = "\n".join(source_parts)
        primary, secondary = check_constraints(combined_source, constraints)
        violations = primary.violations + secondary.violations
        if violations:
            all_violations.append(f"[{task_name}] Implementation constraint violations:")
            all_violations.extend(f"  - {v}" for v in violations)
    if all_violations:
        return False, "\n".join(all_violations)
    return True, ""


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
) -> bool:
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

    Returns:
        True when verification succeeds within retry budget.
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
            prompt, config.implementation_agent, config.implementation_model,
        )
        impl_msg = f"Running implementation agent (attempt {attempt}/{max_attempts})..."
        with display_spinner_context(impl_msg):
            command_ok, error_feedback = _run_implementation_attempt(command)
        if not command_ok:
            _log_attempt_failed(
                logger, attempt, max_attempts, "implementation agent failed", error_feedback
            )
            continue

        if implementation_constraints_map:
            impl_ok, impl_feedback = _check_implementation_constraints(
                workspace=test_dir.parent,
                implementation_constraints_map=implementation_constraints_map,
            )
            if not impl_ok:
                error_feedback = impl_feedback
                display_test_failure_output(error_feedback)
                _log_attempt_failed(
                    logger, attempt, max_attempts, "implementation constraints failed", error_feedback
                )
                continue

        if objective is not None:
            existing_test_paths = _collect_existing_test_paths(objective, test_dir.parent)
            if existing_test_paths:
                with display_spinner_context("Running existing test regression gate..."):
                    reg_passed, reg_output = _run_pytest_targets(
                        workspace=test_dir.parent,
                        targets=existing_test_paths,
                        use_sandbox=use_sandbox,
                    )
                if not reg_passed:
                    error_feedback = f"REGRESSION FAILURE: existing tests broke:\n{reg_output}"
                    display_test_failure_output(error_feedback)
                    _log_attempt_failed(
                        logger, attempt, max_attempts, "regression gate failed", error_feedback
                    )
                    continue

        with display_spinner_context("Verifying tests..."):
            passed, error_feedback = _verify_tests(
                test_dir=test_dir,
                use_sandbox=use_sandbox,
                state=state,
                objective=objective,
            )
        if passed:
            logger.emit(
                "attempt_succeeded", success=True, attempt=attempt, max_attempts=max_attempts
            )
            return True
        display_test_failure_output(error_feedback)
        _log_attempt_failed(logger, attempt, max_attempts, "verification failed", error_feedback)
    return False


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


def _run_implementation_attempt(command: list[str]) -> tuple[bool, str]:
    """Run one implementation-agent command and return retry feedback on failure.

    Args:
        command: Fully built implementation-agent command.

    Returns:
        Tuple of success flag and error feedback text.
    """
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except FileNotFoundError as exc:
        return (
            False,
            _format_agent_failure_feedback(
                returncode=-1,
                stdout="",
                stderr=f"Agent binary not found: {exc}",
            ),
        )

    if result.returncode != 0:
        return (
            False,
            _format_agent_failure_feedback(
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            ),
        )
    return True, ""


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
        trigger="evaluate",
        profiles_path=profiles_path,
    )


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
        holdout_specs = _collect_holdout_eval_specs(state, objective)

    public_passed, public_output = _run_pytest_targets(
        workspace=test_dir.parent,
        targets=[test_dir],
        use_sandbox=use_sandbox,
    )
    if not public_passed:
        return False, public_output

    if not holdout_specs:
        return True, ""

    holdout_passed, holdout_output = _run_holdout_eval_checks(
        test_dir=test_dir,
        use_sandbox=use_sandbox,
        holdout_specs=holdout_specs,
    )
    if holdout_passed:
        return True, ""
    if holdout_output.startswith("HOLDOUT EVAL CONFIG ERROR:"):
        return False, holdout_output
    return False, _redacted_holdout_failure_feedback(holdout_output, holdout_specs)


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
        safe_task_name = _validated_unit_name(
            task_name,
            "EVALUATION CONFIG ERROR",
        )
        public_target = test_dir / f"test_{safe_task_name}.py"
        if not public_target.exists():
            return (
                False,
                f"Verification unit `{task_name}` failed: "
                f"missing train suite file `{public_target}`.",
            )

        public_passed, public_output = _run_pytest_targets(
            workspace=workspace,
            targets=[public_target],
            use_sandbox=use_sandbox,
        )
        if not public_passed:
            return (
                False,
                f"Verification unit `{task_name}` failed public "
                f"train-suite checks:\n{public_output}",
            )

        task_objective = _objective_for_task(objective, task_name)
        if not task_objective.holdout_evals:
            continue

        holdout_passed, holdout_output = _run_holdout_eval_checks(
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
            _redacted_holdout_failure_feedback(
                holdout_output,
                {task_name: task_objective},
                unit_name=task_name,
            ),
        )

    return True, ""


def _collect_holdout_eval_specs(
    state: CheckpointState,
    objective: ParsedObjective | None,
) -> dict[str, ParsedObjective]:
    """Collect task-scoped objectives that include holdout evals.

    Args:
        state: Checkpoint state being processed.
        objective: Parsed objective data for the current run.

    Returns:
        Computed text result for this operation.
    """
    if objective is None:
        return {}

    holdout_specs = {}
    for progress in state.task_progress:
        if not progress.train_suite_source:
            continue
        task_objective = _objective_for_task(objective, progress.name)
        if task_objective.holdout_evals:
            holdout_specs[progress.name] = task_objective
    return holdout_specs


def _run_pytest_targets(
    workspace: Path,
    targets: list[Path],
    use_sandbox: bool,
    timeout_sec: int = HOST_PYTEST_TIMEOUT_SEC,
) -> tuple[bool, str]:
    """Run pytest for targets via host or Docker sandbox.

    Args:
        workspace: Workspace root directory.
        targets: Value for `targets` used by `_run_pytest_targets`.
        use_sandbox: Whether verification runs inside the Docker sandbox.

    Returns:
        True when the operation succeeds; otherwise False.
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

    env = os.environ.copy()
    workspace_python_path = str(workspace)
    existing_python_path = env.get(_PYTHONPATH_ENV, "")
    if existing_python_path:
        env[_PYTHONPATH_ENV] = f"{workspace_python_path}{os.pathsep}{existing_python_path}"
    else:
        env[_PYTHONPATH_ENV] = workspace_python_path

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


def _run_holdout_eval_checks(
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
        True when the operation succeeds; otherwise False.
    """
    workspace = test_dir.parent
    with tempfile.TemporaryDirectory(dir=workspace, prefix=".crucis_holdout_eval_") as temp_dir:
        holdout_dir = Path(temp_dir)
        try:
            holdout_paths = _write_holdout_eval_tests(holdout_dir, holdout_specs)
        except ValueError as exc:
            return False, str(exc)

        if not holdout_paths:
            return True, ""

        return _run_pytest_targets(workspace, holdout_paths, use_sandbox)


def _write_holdout_eval_tests(
    holdout_dir: Path,
    holdout_specs: dict[str, ParsedObjective],
) -> list[Path]:
    """Write holdout eval tests and return generated file paths.

    Args:
        holdout_dir: Directory path for `holdout_dir`.
        holdout_specs: Holdout verification specs grouped by task name.

    Returns:
        Resolved filesystem path for this operation.
    """
    written_paths = []
    for task_name, task_objective in holdout_specs.items():
        safe_task_name = _validated_unit_name(
            task_name,
            "HOLDOUT EVAL CONFIG ERROR",
        )
        test_path = holdout_dir / f"test_holdout_{safe_task_name}.py"
        test_path.write_text(
            _build_holdout_eval_test_source(task_objective),
            encoding=TEXT_ENCODING,
        )
        written_paths.append(test_path)
    return written_paths


def _build_holdout_eval_test_source(objective: ParsedObjective) -> str:
    """Build hidden pytest source for one task objective.

    Args:
        objective: Parsed objective data for the current run.

    Returns:
        Computed text result for this operation.
    """
    module_candidates = _module_candidates_from_targets(objective.target_files)
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

    for idx, case in enumerate(objective.holdout_evals):
        lines.append(f"def test_holdout_case_{idx}():")
        lines.append(f"    assert TARGET_FUNC{case.input} == {case.output}")
        lines.append("")

    return "\n".join(lines)


def _module_candidates_from_targets(target_files: list[str]) -> list[str]:
    """Build import-module candidates from configured target file paths.

    Args:
        target_files: Repo-relative Python files to include for this operation.

    Returns:
        Computed text result for this operation.
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

        _append_unique(candidates, ".".join(parts))
        _append_unique(candidates, parts[-1])
        if len(parts) > 1 and parts[0] in {"src", "app", "lib"}:
            _append_unique(candidates, ".".join(parts[1:]))

    return candidates


def _append_unique(items: list[str], value: str) -> None:
    """append unique.

    Args:
        items: Value for `items` used by `_append_unique`.
        value: Candidate field value being validated.
    """
    if value and value not in items:
        items.append(value)


def _redacted_holdout_failure_feedback(
    holdout_output: str,
    holdout_specs: dict[str, ParsedObjective],
    unit_name: str | None = None,
) -> str:
    """Return non-sensitive feedback text for holdout failures.

    Args:
        holdout_output: Pytest output from holdout verification execution.
        holdout_specs: Holdout verification specs grouped by task name.
        unit_name: Name value for `unit_name`.

    Returns:
        Computed text result for this operation.
    """
    failed_cases = _count_failed_cases(holdout_output)
    task_count = len(holdout_specs)
    prefix = f"Verification unit `{unit_name}` failed holdout evaluations. " if unit_name else ""
    return (
        f"{prefix}Holdout evaluations failed ({failed_cases} case(s) across "
        f"{task_count} task(s)). Holdout details are redacted. "
        "Generalize your implementation and handle broader inputs."
    )


def _format_agent_failure_feedback(
    returncode: int,
    stdout: str,
    stderr: str,
    max_chars: int = 1200,
) -> str:
    """Format bounded retry feedback for evaluation-agent failures.

    Args:
        returncode: Value for `returncode` used by `_format_agent_failure_feedback`.
        stdout: Process stdout text.
        stderr: Process stderr text.
        max_chars: Value for `max_chars` used by `_format_agent_failure_feedback`.

    Returns:
        Computed text result for this operation.
    """
    parts = [f"EVALUATION AGENT FAILED (exit code {returncode})."]
    stderr_excerpt = _bounded_excerpt(stderr, max_chars)
    stdout_excerpt = _bounded_excerpt(stdout, max_chars)
    if stderr_excerpt:
        parts.append(f"stderr:\n{stderr_excerpt}")
    if stdout_excerpt:
        parts.append(f"stdout:\n{stdout_excerpt}")
    parts.append("Fix the failure and retry evaluation.")
    return "\n\n".join(parts)


def _bounded_excerpt(text: str, limit: int) -> str:
    """Trim output text for bounded retry feedback.

    Args:
        text: Input text to transform or truncate.
        limit: Maximum number of characters to keep.

    Returns:
        Computed text result for this operation.
    """
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "\n...[truncated]..."


def _count_failed_cases(pytest_output: str) -> int:
    """Count failing pytest cases from output without exposing payloads.

    Args:
        pytest_output: Value for `pytest_output` used by `_count_failed_cases`.

    Returns:
        Result of `_count_failed_cases`.
    """
    count = 0
    for line in pytest_output.splitlines():
        if line.startswith("FAILED "):
            count += 1
    return count if count > 0 else 1


def _objective_for_task(objective: ParsedObjective, task_name: str) -> ParsedObjective:
    """Create a task-scoped objective for prompts and adversarial review.

    Args:
        objective: Parsed objective data for the current run.
        task_name: Task name within the objective.

    Returns:
        Result of `_objective_for_task`.
    """
    for task in objective.tasks:
        if task.name == task_name:
            train_evals = task.train_evals or objective.train_evals
            holdout_evals = task.holdout_evals or objective.holdout_evals
            target_files = task.target_files or objective.target_files
            return ParsedObjective(
                name=task.name,
                description=task.description or objective.description,
                train_evals=list(train_evals),
                holdout_evals=list(holdout_evals),
                signature=task.signature or objective.signature,
                tests_constraint_profile=task.tests_constraint_profile or objective.tests_constraint_profile,
                implementation_constraint_profile=task.implementation_constraint_profile or objective.implementation_constraint_profile,
                target_files=list(target_files),
                tasks=list(objective.tasks),
                verification_granularity=objective.verification_granularity,
            )

    return ParsedObjective(
        name=task_name,
        description=objective.description,
        train_evals=list(objective.train_evals),
        holdout_evals=list(objective.holdout_evals),
        signature=objective.signature,
        tests_constraint_profile=objective.tests_constraint_profile,
        implementation_constraint_profile=objective.implementation_constraint_profile,
        target_files=list(objective.target_files),
        tasks=list(objective.tasks),
        verification_granularity=objective.verification_granularity,
    )


def _format_adversarial_feedback(report) -> str:
    """Format adversarial findings into generation feedback text.

    Args:
        report: Adversarial report payload for the current task.

    Returns:
        Computed text result for this operation.
    """
    parts = []
    if report.generalization_gaps:
        parts.append("Generalization gaps to add (pick the most important):")
        parts.extend(f"  - {item}" for item in report.generalization_gaps[:5])
    if report.probe_succeeded:
        parts.append("Warning: a cheating probe implementation passed your train suite.")
        parts.append("Add tests with dynamic/random inputs to prevent hardcoding.")
    return "\n".join(parts)


def _write_generated_tests(state: CheckpointState, test_dir: Path) -> list[Path]:
    """Write approved train suites from checkpoint state to disk.

    Args:
        state: Checkpoint state being processed.
        test_dir: Directory containing generated train-suite tests.

    Returns:
        Resolved filesystem path for this operation.
    """
    written_paths = []
    for progress in state.task_progress:
        if not progress.train_suite_source:
            continue
        safe_name = _validated_unit_name(
            progress.name,
            "EVALUATION CONFIG ERROR",
        )
        path = test_dir / f"test_{safe_name}.py"
        path.write_text(progress.train_suite_source, encoding=TEXT_ENCODING)
        written_paths.append(path)
    return written_paths


def _validated_unit_name(name: str, error_prefix: str) -> str:
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


def _load_policy_or_none(workspace: Path) -> OptimizerPolicy | None:
    """Load active policy while tolerating malformed/unavailable state.

    Args:
        workspace: Workspace root directory.

    Returns:
        None.
    """
    try:
        return load_active_policy(workspace)
    except Exception as exc:
        display_error(f"Could not load active optimizer policy: {exc}")
        return None


def _resolve_profiles_path(workspace: Path, profiles_path: Path) -> Path:
    """Resolve profiles path relative to objective workspace when needed.

    Args:
        workspace: Workspace root directory.
        profiles_path: Path passed from CLI/config.

    Returns:
        Absolute profiles path.
    """
    if profiles_path.is_absolute():
        return profiles_path.resolve()

    workspace_relative = workspace / profiles_path
    if workspace_relative.exists():
        return workspace_relative.resolve()
    return profiles_path.resolve()


def _enqueue_optimizer_job(
    workspace: Path,
    objective: ParsedObjective,
    state: CheckpointState,
    trigger: str,
    profiles_path: Path | None = None,
) -> None:
    """Queue a background optimizer job, logging non-fatal enqueue failures.

    Args:
        workspace: Workspace root directory.
        objective: Parsed objective data for the current run.
        state: Checkpoint state being processed.
        trigger: Trigger label indicating why optimization was enqueued.
        profiles_path: Optional path to the profiles file used for this run.
    """
    try:
        enqueue_background_optimization(
            workspace=workspace,
            objective=objective,
            checkpoint=state,
            trigger=trigger,
            profiles_path=profiles_path,
        )
    except Exception as exc:
        display_error(f"Background optimization enqueue failed: {exc}")
