"""Background GEPA optimize_anything integration for Crucis."""

from __future__ import annotations

__all__ = [
    "AggregatedMetrics",
    "BlackboxRunResult",
    "OptimizationJob",
    "_acquire_worker_lock",
    "_bounded_excerpt",
    "_build_objective_examples",
    "_build_run_report",
    "_build_task_examples",
    "_build_verifier_examples",
    "_checkpoint_entries_for_example",
    "_classify_failure",
    "_copy_file",
    "_copy_project_config_files",
    "_copy_root_python_siblings_if_needed",
    "_copy_roots_for_targets",
    "_evaluate_and_build_result",
    "_evaluate_policy_on_examples",
    "_is_optimizer_worker_command",
    "_is_stale_lock",
    "_job_result",
    "_load_lock_payload",
    "_lock_age_seconds",
    "_metrics_dict",
    "_pid_command_line",
    "_pid_is_alive",
    "_prepare_isolated_workspace",
    "_prepare_profiles_path_for_isolated_workspace",
    "_process_job",
    "_process_job_file",
    "_release_worker_lock",
    "_resolve_profiles_path",
    "_run_blackbox_task",
    "_run_gepa_optimization",
    "_score_candidate_on_example",
    "_setup_isolated_eval_files",
    "_should_promote",
    "_split_examples",
    "_target_files_for_example",
    "_task_scoped_objective",
    "_try_create_lock_file",
    "_utc_now",
    "_validate_job_prerequisites",
    "enqueue_background_optimization",
    "main",
    "run_optimizer_worker",
    "spawn_optimizer_worker",
]

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

try:
    from gepa.optimize_anything import (
        EngineConfig,
        GEPAConfig,
        ReflectionConfig,
        optimize_anything,
    )

    _GEPA_AVAILABLE = True
    _GEPA_IMPORT_ERROR: Exception | None = None
except Exception as _exc:
    EngineConfig = None  # type: ignore[assignment,misc]
    GEPAConfig = None  # type: ignore[assignment,misc]
    ReflectionConfig = None  # type: ignore[assignment,misc]
    optimize_anything = None  # type: ignore[assignment]
    _GEPA_AVAILABLE = False
    _GEPA_IMPORT_ERROR = _exc

from crucis.defaults import TEXT_ENCODING
from crucis.execution.constants import (
    DISABLE_OPTIMIZER_ENV,
    EXCERPT_MAX_CHARS,
    LOCK_STALE_MAX_AGE_SEC,
    MS_PER_SEC,
    PYTHONPATH_ENV,
)
from crucis.models import CheckpointState, ParsedObjective, VerificationGranularity
from crucis.persistence.events import EventLogger
from crucis.persistence.policy import (
    POLICY_OVERRIDE_ENV,
    OptimizerPolicy,
    OptimizerState,
    OptimizerStatus,
    load_active_policy,
    lock_path,
    queue_dir,
    runs_dir,
    save_active_policy,
    save_candidate_policy,
    save_optimizer_status,
)
from crucis.persistence.settings import REFLECTION_LM_PREFIX_TO_ENV, RuntimeSettings, load_runtime_settings

_WORKER_CMD_MARKER = "crucis.gepa_optimizer"

_COPYTREE_IGNORES = (
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    ".DS_Store",
)

_PROJECT_CONFIG_FILES = (
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "requirements-dev.txt",
    "pytest.ini",
    "tox.ini",
)

_JSON_MODE = "json"
_TASK_KEY = "task"
_OBJECTIVE_KEY = "objective"
_MEAN_FINAL_SCORE_KEY = "mean_final_score"


class OptimizationJob(BaseModel):
    """Queued background optimization job payload."""

    job_id: str
    trigger: str
    created_at: str
    objective_snapshot: dict
    checkpoint_snapshot: dict
    profiles_path: str | None = None


@dataclass
class BlackboxRunResult:
    """Result of one black-box Crucis verifier execution."""

    returncode: int
    stdout: str
    stderr: str
    duration_sec: float


@dataclass
class AggregatedMetrics:
    """Aggregated evaluation metrics over examples."""

    mean_final_score: float
    mean_correctness: float
    mean_speed: float
    num_examples: int


def enqueue_background_optimization(
    workspace: Path,
    objective: ParsedObjective,
    checkpoint: CheckpointState,
    trigger: str,
    profiles_path: Path | None = None,
) -> bool:
    """Queue an optimization job and spawn a background worker process.

    Args:
        workspace: Workspace root directory.
        objective: Parsed objective data for the current run.
        checkpoint: Value for `checkpoint` used by `enqueue_background_optimization`.
        trigger: Trigger label indicating why optimization was enqueued.
        profiles_path: Optional path to the constraints profiles YAML used for this run.

    Returns:
        True when the operation succeeds; otherwise False.
    """
    if os.environ.get(DISABLE_OPTIMIZER_ENV) == "1":
        return False

    try:
        settings = load_runtime_settings(workspace)
    except Exception:
        return False

    if not settings.optimizer.enabled:
        return False

    qdir = queue_dir(workspace)
    qdir.mkdir(parents=True, exist_ok=True)

    queued_jobs = sorted(qdir.glob("*.json"))
    if len(queued_jobs) >= settings.optimizer.queue_max_jobs:
        overflow = len(queued_jobs) - settings.optimizer.queue_max_jobs + 1
        for path in queued_jobs[:overflow]:
            path.unlink(missing_ok=True)

    job = OptimizationJob(
        job_id=uuid.uuid4().hex,
        trigger=trigger,
        created_at=_utc_now(),
        objective_snapshot=objective.model_dump(mode=_JSON_MODE),
        checkpoint_snapshot=checkpoint.model_dump(mode=_JSON_MODE),
        profiles_path=str(_resolve_profiles_path(workspace, profiles_path)),
    )
    job_path = qdir / f"{int(time.time() * MS_PER_SEC)}_{job.job_id}.json"
    job_path.write_text(job.model_dump_json(indent=2), encoding=TEXT_ENCODING)

    return spawn_optimizer_worker(workspace)


def spawn_optimizer_worker(workspace: Path) -> bool:
    """Spawn a detached one-shot optimizer worker.

    Args:
        workspace: Workspace root directory.

    Returns:
        True when the operation succeeds; otherwise False.
    """
    try:
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "crucis.gepa_optimizer",
                "--workspace",
                str(workspace),
                "--once",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        return False
    return True


def run_optimizer_worker(workspace: Path, once: bool = True) -> int:
    """Drain queued optimization jobs under a single-worker lock.

    Args:
        workspace: Workspace root directory.
        once: Value for `once` used by `run_optimizer_worker`.

    Returns:
        Result of running the requested operation.
    """
    logger = EventLogger(workspace, "optimizer_worker")
    run_succeeded = True
    stop_message: str | None = None
    if logger.path is not None:
        print(f"Run log: {logger.path}")
    logger.emit(
        "worker_started",
        details={"workspace": str(workspace), "mode": "once" if once else "loop"},
    )
    try:
        settings = load_runtime_settings(workspace)
        if not settings.optimizer.enabled:
            stop_message = "optimizer disabled"
            return 0
        if not _acquire_worker_lock(workspace):
            stop_message = "worker lock already held"
            return 0
        try:
            while True:
                pending = sorted(queue_dir(workspace).glob("*.json"))
                logger.emit("queue_polled", details={"pending_jobs": len(pending)})
                if not pending:
                    save_optimizer_status(
                        workspace,
                        OptimizerStatus(
                            state=OptimizerState.idle,
                            updated_at=_utc_now(),
                        ),
                    )
                    if once:
                        break
                    time.sleep(2)
                    continue

                for job_path in pending:
                    logger.emit("job_processing_started", details={"job_file": job_path.name})
                    _process_job_file(workspace, job_path, settings)
                    logger.emit("job_processing_finished", details={"job_file": job_path.name})

                if once:
                    break
        finally:
            _release_worker_lock(workspace)
    except Exception as exc:
        run_succeeded = False
        logger.emit("worker_failed", success=False, message=str(exc))
        raise
    finally:
        logger.emit("worker_stopped", success=run_succeeded, message=stop_message)
        logger.close()

    return 0


def _process_job_file(workspace: Path, job_path: Path, settings: RuntimeSettings) -> None:
    """Process one queued job file and persist run artifacts/status.

    Args:
        workspace: Workspace root directory.
        job_path: Path to queued optimization job JSON.
        settings: Loaded runtime optimizer settings.
    """
    try:
        payload = json.loads(job_path.read_text(encoding=TEXT_ENCODING))
        job = OptimizationJob.model_validate(payload)
    except Exception as exc:
        save_optimizer_status(
            workspace,
            OptimizerStatus(
                state=OptimizerState.failed,
                message=f"invalid job payload: {exc}",
                updated_at=_utc_now(),
            ),
        )
        job_path.unlink(missing_ok=True)
        return

    run_dir = runs_dir(workspace) / job.job_id
    run_dir.mkdir(parents=True, exist_ok=True)

    save_optimizer_status(
        workspace,
        OptimizerStatus(
            state=OptimizerState.running,
            last_run_id=job.job_id,
            last_trigger=job.trigger,
            message="running GEPA optimize_anything",
            updated_at=_utc_now(),
        ),
    )

    try:
        outcome = _process_job(workspace, job, run_dir, settings)
    except Exception as exc:
        outcome = {
            "state": OptimizerState.failed,
            "job_id": job.job_id,
            "trigger": job.trigger,
            "message": f"optimizer exception: {exc}",
            "updated_at": _utc_now(),
        }

    (run_dir / "result.json").write_text(
        json.dumps(outcome, indent=2),
        encoding=TEXT_ENCODING,
    )
    (run_dir / "report.md").write_text(
        _build_run_report(outcome),
        encoding=TEXT_ENCODING,
    )

    save_optimizer_status(
        workspace,
        OptimizerStatus(
            state=str(outcome.get("state", OptimizerState.completed)),
            last_run_id=job.job_id,
            last_trigger=job.trigger,
            promoted=outcome.get("promoted"),
            message=outcome.get("message"),
            updated_at=_utc_now(),
            last_candidate_score=outcome.get("candidate", {}).get(_MEAN_FINAL_SCORE_KEY),
            last_baseline_score=outcome.get("baseline", {}).get(_MEAN_FINAL_SCORE_KEY),
            active_policy_version=outcome.get("active_policy_version"),
            candidate_ready=bool(outcome.get("candidate_ready")),
            candidate_run_id=outcome.get("candidate_run_id"),
        ),
    )
    job_path.unlink(missing_ok=True)


def _validate_job_prerequisites(
    workspace: Path,
    job: OptimizationJob,
    settings: RuntimeSettings,
) -> dict[str, Any] | None:
    """Check profiles and GEPA availability before running a job.

    Args:
        workspace: Workspace root directory.
        job: Optimization job payload.
        settings: Loaded runtime optimizer settings.

    Returns:
        Failure result dict if prerequisites are missing, None if OK.
    """
    profiles_path = _resolve_profiles_path(
        workspace,
        Path(job.profiles_path) if job.profiles_path else None,
    )
    if not profiles_path.exists():
        return _job_result(
            job,
            OptimizerState.failed,
            message=f"Profiles file not found for optimizer run: {profiles_path}",
        )
    missing_key_message = _missing_reflection_key_message(settings.optimizer.reflection_lm)
    if missing_key_message is not None:
        return _job_result(job, OptimizerState.failed, message=missing_key_message)
    if not _GEPA_AVAILABLE:
        return _job_result(
            job,
            OptimizerState.failed,
            message=f"GEPA dependencies unavailable: {_GEPA_IMPORT_ERROR}",
        )
    return None


def _missing_reflection_key_message(reflection_lm: str) -> str | None:
    """Return an auth-preflight failure message when reflection key is missing.

    Args:
        reflection_lm: Reflection model name from runtime settings.

    Returns:
        Failure message when API key is missing; otherwise None.
    """
    for prefix, env_key in REFLECTION_LM_PREFIX_TO_ENV.items():
        if reflection_lm.startswith(prefix) and not os.environ.get(env_key):
            return (
                f"Missing required environment variable `{env_key}` for "
                f"optimizer reflection_lm `{reflection_lm}`."
            )
    return None


def _process_job(
    workspace: Path,
    job: OptimizationJob,
    run_dir: Path,
    settings: RuntimeSettings,
) -> dict[str, Any]:
    """Execute GEPA optimization for one queued job.

    Args:
        workspace: Workspace root directory.
        job: Optimization job payload.
        run_dir: Directory for optimizer run artifacts.
        settings: Loaded runtime optimizer settings.

    Returns:
        Computed text result for this operation.
    """
    prereq_failure = _validate_job_prerequisites(workspace, job, settings)
    if prereq_failure is not None:
        return prereq_failure

    profiles_path = _resolve_profiles_path(
        workspace,
        Path(job.profiles_path) if job.profiles_path else None,
    )
    objective = ParsedObjective.model_validate(job.objective_snapshot)
    checkpoint = CheckpointState.model_validate(job.checkpoint_snapshot)

    examples = _build_verifier_examples(
        objective,
        checkpoint,
        max_examples=settings.optimizer.max_examples_per_run,
    )
    if not examples:
        return _job_result(
            job, "skipped", message="No eligible verifier examples with approved test suites."
        )

    train_examples, val_examples = _split_examples(
        examples,
        train_ratio=settings.optimizer.train_split_ratio,
    )
    baseline_policy = load_active_policy(workspace)

    result = _run_gepa_optimization(
        workspace,
        settings,
        profiles_path,
        baseline_policy,
        train_examples,
        val_examples,
    )

    best_candidate = result.best_candidate
    if not isinstance(best_candidate, dict):
        return _job_result(
            job,
            OptimizerState.failed,
            message="GEPA returned a non-dict candidate; expected policy dict.",
        )

    candidate_policy = OptimizerPolicy.from_candidate(best_candidate)
    save_candidate_policy(candidate_policy, workspace, job.job_id)

    return _evaluate_and_build_result(
        workspace,
        job,
        objective,
        settings,
        profiles_path,
        baseline_policy,
        candidate_policy,
        val_examples,
        train_examples,
    )


def _job_result(
    job: OptimizationJob,
    state: str,
    **extra: Any,
) -> dict[str, Any]:
    """Build a standard job result dict.

    Args:
        job: Optimization job payload.
        state: Result state string (e.g. 'failed', 'skipped', 'completed').
        **extra: Additional key-value pairs merged into the result.

    Returns:
        Job result dictionary.
    """
    return {
        "state": state,
        "job_id": job.job_id,
        "trigger": job.trigger,
        "updated_at": _utc_now(),
        **extra,
    }


def _metrics_dict(metrics: AggregatedMetrics) -> dict[str, Any]:
    """Convert aggregated metrics to a plain dict for result reporting.

    Args:
        metrics: Aggregated metrics from policy evaluation.

    Returns:
        Dictionary with mean_final_score, mean_correctness, mean_speed, num_examples.
    """
    return {
        "mean_final_score": metrics.mean_final_score,
        "mean_correctness": metrics.mean_correctness,
        "mean_speed": metrics.mean_speed,
        "num_examples": metrics.num_examples,
    }


def _run_gepa_optimization(
    workspace: Path,
    settings: RuntimeSettings,
    profiles_path: Path,
    baseline_policy: OptimizerPolicy,
    train_examples: list[dict[str, Any]],
    val_examples: list[dict[str, Any]],
) -> Any:
    """Run the GEPA optimize_anything loop.

    Args:
        workspace: Workspace root directory.
        settings: Loaded runtime optimizer settings.
        profiles_path: Resolved path to constraint profiles.
        baseline_policy: Current active optimizer policy.
        train_examples: Training split of verifier examples.
        val_examples: Validation split of verifier examples.

    Returns:
        GEPA optimization result object.
    """

    def evaluator(candidate: dict[str, str], example: dict[str, Any]) -> tuple[float, dict]:
        """Score one candidate on one example.

        Args:
            candidate: Candidate policy dictionary under evaluation.
            example: Verifier example payload used during GEPA scoring.

        Returns:
            Tuple of (score, metadata).
        """
        return _score_candidate_on_example(
            workspace=workspace,
            candidate=candidate,
            example=example,
            settings=settings,
            profiles_path=profiles_path,
        )

    gepa_config = GEPAConfig(
        engine=EngineConfig(
            max_metric_calls=settings.optimizer.max_metric_calls,
            capture_stdio=settings.optimizer.capture_stdio,
        ),
        reflection=ReflectionConfig(reflection_lm=settings.optimizer.reflection_lm),
    )
    return optimize_anything(
        seed_candidate=baseline_policy.to_candidate(),
        evaluator=evaluator,
        dataset=train_examples,
        valset=val_examples,
        objective=(
            "Optimize Crucis policy for robust coding outcomes across verifier units. "
            "Prefer correctness and generalization over brittle overfitting."
        ),
        background=(
            "Candidate policy contains four fields: repository_skill, generation_directives, "
            "adversary_directives, evaluation_directives. Keep guidance concise and safe for "
            "holdout-eval secrecy."
        ),
        config=gepa_config,
    )


def _evaluate_and_build_result(
    workspace: Path,
    job: OptimizationJob,
    objective: ParsedObjective,
    settings: RuntimeSettings,
    profiles_path: Path,
    baseline_policy: OptimizerPolicy,
    candidate_policy: OptimizerPolicy,
    val_examples: list[dict[str, Any]],
    train_examples: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate baseline vs candidate and build the final result dict.

    Args:
        workspace: Workspace root directory.
        job: Optimization job payload.
        objective: Parsed objective for verification granularity.
        settings: Loaded runtime optimizer settings.
        profiles_path: Resolved path to constraint profiles.
        baseline_policy: Current active optimizer policy.
        candidate_policy: Optimized candidate policy.
        val_examples: Validation split of verifier examples.
        train_examples: Training split of verifier examples.

    Returns:
        Completed job result dictionary.
    """
    baseline_metrics = _evaluate_policy_on_examples(
        workspace=workspace,
        policy=baseline_policy,
        examples=val_examples,
        settings=settings,
        profiles_path=profiles_path,
    )
    candidate_metrics = _evaluate_policy_on_examples(
        workspace=workspace,
        policy=candidate_policy,
        examples=val_examples,
        settings=settings,
        profiles_path=profiles_path,
    )

    should_promote = _should_promote(
        baseline=baseline_metrics,
        candidate=candidate_metrics,
        min_score_delta=settings.optimizer.min_score_delta,
    )
    promotion_mode = settings.optimizer.promotion_mode

    promoted = False
    candidate_ready = bool(should_promote)
    active_policy_version = "unchanged"
    if should_promote and promotion_mode == "auto":
        save_active_policy(candidate_policy, workspace)
        promoted = True
        candidate_ready = False
        active_policy_version = job.job_id

    if promoted:
        message = "candidate promoted"
    elif candidate_ready:
        message = "candidate ready for manual promotion"
    else:
        message = "candidate not promoted"

    return _job_result(
        job,
        OptimizerState.completed,
        promoted=promoted,
        candidate_ready=candidate_ready,
        candidate_run_id=job.job_id if candidate_ready else None,
        promotion_mode=promotion_mode,
        verification_granularity=objective.verification_granularity.value,
        message=message,
        train_examples=len(train_examples),
        val_examples=len(val_examples),
        baseline=_metrics_dict(baseline_metrics),
        candidate=_metrics_dict(candidate_metrics),
        active_policy_version=active_policy_version,
    )


def _build_verifier_examples(
    objective: ParsedObjective,
    checkpoint: CheckpointState,
    max_examples: int,
) -> list[dict[str, Any]]:
    """Build verifier examples from objective + checkpoint snapshots.

    Args:
        objective: Parsed objective data for the current run.
        checkpoint: Value for `checkpoint` used by `_build_verifier_examples`.
        max_examples: Maximum number of examples to include in a run.

    Returns:
        Computed text result for this operation.
    """
    if objective.verification_granularity == VerificationGranularity.objective:
        return _build_objective_examples(objective, checkpoint, max_examples)
    return _build_task_examples(objective, checkpoint, max_examples)


def _build_task_examples(
    objective: ParsedObjective,
    checkpoint: CheckpointState,
    max_examples: int,
) -> list[dict[str, Any]]:
    """Build task-scoped verifier examples from objective + checkpoint.

    Args:
        objective: Parsed objective data for the current run.
        checkpoint: Value for `checkpoint` used by `_build_task_examples`.
        max_examples: Maximum number of examples to include in a run.

    Returns:
        Computed text result for this operation.
    """
    progress_by_name = {
        progress.name: progress
        for progress in checkpoint.task_progress
        if progress.train_suite_source
    }

    task_names = [task.name for task in objective.tasks] if objective.tasks else [objective.name]

    examples: list[dict[str, Any]] = []
    for task_name in task_names:
        progress = progress_by_name.get(task_name)
        if progress is None or not progress.train_suite_source:
            continue

        scoped_objective = _task_scoped_objective(objective, task_name)
        if not scoped_objective.target_files:
            continue
        examples.append(
            {
                "unit_kind": _TASK_KEY,
                "task_name": task_name,
                "unit_name": task_name,
                "objective_snapshot": scoped_objective.model_dump(mode=_JSON_MODE),
                "train_suite_source": progress.train_suite_source,
            }
        )

    examples.sort(key=lambda item: str(item["unit_name"]))
    return examples[:max_examples]


def _build_objective_examples(
    objective: ParsedObjective,
    checkpoint: CheckpointState,
    max_examples: int,
) -> list[dict[str, Any]]:
    """Build objective-scoped verifier examples from objective + checkpoint.

    Args:
        objective: Parsed objective data for the current run.
        checkpoint: Value for `checkpoint` used by `_build_objective_examples`.
        max_examples: Maximum number of examples to include in a run.

    Returns:
        Computed text result for this operation.
    """
    train_suite_map = {
        progress.name: progress.train_suite_source
        for progress in checkpoint.task_progress
        if progress.train_suite_source
    }
    if not train_suite_map:
        return []

    if not _target_files_for_example(objective, _OBJECTIVE_KEY):
        return []

    return [
        {
            "unit_kind": _OBJECTIVE_KEY,
            "unit_name": objective.name,
            "objective_snapshot": objective.model_dump(mode=_JSON_MODE),
            "train_suite_map": train_suite_map,
        }
    ][:max_examples]


def _task_scoped_objective(objective: ParsedObjective, task_name: str) -> ParsedObjective:
    """Resolve one task objective with top-level fallback semantics.

    Args:
        objective: Parsed objective data for the current run.
        task_name: Task name within the objective.

    Returns:
        Result of `_task_scoped_objective`.
    """
    for task in objective.tasks:
        if task.name != task_name:
            continue
        train_evals = task.train_evals or objective.train_evals
        holdout_evals = task.holdout_evals or objective.holdout_evals
        target_files = task.target_files or objective.target_files
        return ParsedObjective(
            name=task.name,
            description=task.description or objective.description,
            signature=task.signature or objective.signature,
            train_evals=list(train_evals),
            holdout_evals=list(holdout_evals),
            tests_constraint_profile=task.tests_constraint_profile or objective.tests_constraint_profile,
            implementation_constraint_profile=task.implementation_constraint_profile or objective.implementation_constraint_profile,
            target_files=list(target_files),
            tasks=[],
            verification_granularity=objective.verification_granularity,
        )

    return ParsedObjective(
        name=task_name,
        description=objective.description,
        signature=objective.signature,
        train_evals=list(objective.train_evals),
        holdout_evals=list(objective.holdout_evals),
        tests_constraint_profile=objective.tests_constraint_profile,
        implementation_constraint_profile=objective.implementation_constraint_profile,
        target_files=list(objective.target_files),
        tasks=[],
        verification_granularity=objective.verification_granularity,
    )


def _split_examples(
    examples: list[dict[str, Any]],
    train_ratio: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deterministically split examples into train/validation sets.

    Args:
        examples: Verifier examples available for train/validation split.
        train_ratio: Fraction of examples assigned to training split.

    Returns:
        Computed text result for this operation.
    """
    if len(examples) <= 1:
        return list(examples), list(examples)

    train_count = int(len(examples) * train_ratio)
    train_count = max(1, min(train_count, len(examples) - 1))
    return list(examples[:train_count]), list(examples[train_count:])


def _evaluate_policy_on_examples(
    workspace: Path,
    policy: OptimizerPolicy,
    examples: list[dict[str, Any]],
    settings: RuntimeSettings,
    profiles_path: Path | None = None,
) -> AggregatedMetrics:
    """Evaluate one policy over a list of examples.

    Args:
        workspace: Workspace root directory.
        policy: Active optimizer policy used for prompt steering.
        examples: Verifier examples available for train/validation split.
        settings: Loaded runtime optimizer settings.
        profiles_path: Optional path to constraint profiles for black-box runs.

    Returns:
        Result of `_evaluate_policy_on_examples`.
    """
    if not examples:
        return AggregatedMetrics(0.0, 0.0, 0.0, 0)

    final_scores: list[float] = []
    correctness_scores: list[float] = []
    speed_scores: list[float] = []

    for example in examples:
        score, side_info = _score_candidate_on_example(
            workspace=workspace,
            candidate=policy.to_candidate(),
            example=example,
            settings=settings,
            profiles_path=profiles_path,
        )
        final_scores.append(score)
        metric_scores = side_info.get("scores", {})
        correctness_scores.append(float(metric_scores.get("correctness", 0.0)))
        speed_scores.append(float(metric_scores.get("speed", 0.0)))

    count = len(examples)
    return AggregatedMetrics(
        mean_final_score=sum(final_scores) / count,
        mean_correctness=sum(correctness_scores) / count,
        mean_speed=sum(speed_scores) / count,
        num_examples=count,
    )


def _score_candidate_on_example(
    workspace: Path,
    candidate: dict[str, str],
    example: dict[str, Any],
    settings: RuntimeSettings,
    profiles_path: Path | None = None,
) -> tuple[float, dict[str, Any]]:
    """Score one candidate policy on one verifier example.

    Args:
        workspace: Workspace root directory.
        candidate: Candidate policy dictionary under evaluation.
        example: Verifier example payload used during GEPA scoring.
        settings: Loaded runtime optimizer settings.
        profiles_path: Optional path to constraint profiles for black-box runs.

    Returns:
        Computed text result for this operation.
    """
    result = _run_blackbox_task(
        workspace=workspace,
        candidate=candidate,
        example=example,
        timeout_sec=settings.optimizer.evaluator_timeout_sec,
        profiles_path=profiles_path,
    )

    correctness = 1.0 if result.returncode == 0 else 0.0
    speed = max(
        0.0,
        1.0 - (result.duration_sec / float(settings.optimizer.evaluator_timeout_sec)),
    )
    final_score = (
        settings.optimizer.pass_weight * correctness + settings.optimizer.speed_weight * speed
    )
    side_info: dict[str, Any] = {
        "scores": {
            "correctness": correctness,
            "speed": speed,
        },
        "duration_sec": result.duration_sec,
        "failure_type": _classify_failure(result.returncode, result.stdout, result.stderr),
        "stdout_excerpt": _bounded_excerpt(result.stdout, EXCERPT_MAX_CHARS),
        "stderr_excerpt": _bounded_excerpt(result.stderr, EXCERPT_MAX_CHARS),
    }
    return final_score, side_info


def _run_blackbox_task(
    workspace: Path,
    candidate: dict[str, str],
    example: dict[str, Any],
    timeout_sec: int,
    profiles_path: Path | None = None,
) -> BlackboxRunResult:
    """Run an isolated verifier evaluation for one example.

    Args:
        workspace: Workspace root directory.
        candidate: Candidate policy dictionary under evaluation.
        example: Verifier example payload used during GEPA scoring.
        timeout_sec: Per-example timeout in seconds for black-box execution.
        profiles_path: Optional path to constraint profiles for black-box runs.

    Returns:
        Result of `_run_blackbox_task`.
    """
    started = time.perf_counter()
    unit_kind = str(example.get("unit_kind", _TASK_KEY))
    objective = ParsedObjective.model_validate(example["objective_snapshot"])
    resolved_profiles_path = _resolve_profiles_path(workspace, profiles_path)

    with tempfile.TemporaryDirectory(prefix=".crucis_gepa_eval_", dir=workspace) as td:
        temp_workspace = Path(td)
        objective_path, checkpoint_path, isolated_profiles_path = _setup_isolated_eval_files(
            workspace, temp_workspace, objective, example, unit_kind, resolved_profiles_path,
        )

        env = os.environ.copy()
        project_root = str(Path(__file__).resolve().parent.parent.parent)
        paths_to_add = [str(workspace), project_root]
        existing_pypath = env.get(PYTHONPATH_ENV, "")
        new_entries = os.pathsep.join(paths_to_add)
        env[PYTHONPATH_ENV] = f"{new_entries}{os.pathsep}{existing_pypath}" if existing_pypath else new_entries
        env[POLICY_OVERRIDE_ENV] = json.dumps(candidate)
        env[DISABLE_OPTIMIZER_ENV] = "1"

        command = [
            sys.executable,
            "-m",
            "crucis",
            "evaluate",
            "--objective",
            str(objective_path),
            "--checkpoint",
            str(checkpoint_path),
            "--profiles",
            str(isolated_profiles_path),
            "--no-sandbox",
        ]

        try:
            completed = subprocess.run(
                command,
                cwd=temp_workspace,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                env=env,
            )
            returncode = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            returncode = -1
            stdout = exc.stdout or ""
            stderr = f"Evaluation timed out after {timeout_sec}s"

    duration_sec = time.perf_counter() - started
    return BlackboxRunResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        duration_sec=duration_sec,
    )


def _setup_isolated_eval_files(
    workspace: Path,
    temp_workspace: Path,
    objective: ParsedObjective,
    example: dict[str, Any],
    unit_kind: str,
    resolved_profiles_path: Path,
) -> tuple[Path, Path, Path]:
    """Prepare objective, checkpoint, and profiles in an isolated workspace.

    Args:
        workspace: Source workspace root.
        temp_workspace: Temporary isolated workspace directory.
        objective: Parsed objective for this evaluation.
        example: Verifier example payload.
        unit_kind: Verifier unit kind (task or objective).
        resolved_profiles_path: Resolved profiles path from source workspace.

    Returns:
        Tuple of (objective_path, checkpoint_path, isolated_profiles_path).
    """
    _prepare_isolated_workspace(
        source_workspace=workspace,
        destination_workspace=temp_workspace,
        target_files=_target_files_for_example(objective, unit_kind),
    )
    isolated_profiles_path = _prepare_profiles_path_for_isolated_workspace(
        source_workspace=workspace,
        destination_workspace=temp_workspace,
        profiles_path=resolved_profiles_path,
    )

    objective_payload = objective.model_dump(mode=_JSON_MODE)
    if unit_kind == _TASK_KEY:
        objective_payload["tasks"] = []
    objective_path = temp_workspace / "objective.yaml"
    objective_path.write_text(
        yaml.safe_dump(objective_payload, sort_keys=False),
        encoding=TEXT_ENCODING,
    )

    checkpoint_payload = {"task_progress": _checkpoint_entries_for_example(example)}
    checkpoint_path = temp_workspace / ".checkpoint.json"
    checkpoint_path.write_text(
        json.dumps(checkpoint_payload, indent=2),
        encoding=TEXT_ENCODING,
    )

    return objective_path, checkpoint_path, isolated_profiles_path


def _checkpoint_entries_for_example(example: dict[str, Any]) -> list[dict[str, Any]]:
    """Build checkpoint task_progress payload for one verifier example.

    Args:
        example: Verifier example payload used during GEPA scoring.

    Returns:
        Checkpoint entries for isolated evaluation.
    """
    unit_kind = str(example.get("unit_kind", _TASK_KEY))
    if unit_kind == _OBJECTIVE_KEY:
        train_suite_map = dict(example.get("train_suite_map", {}))
        entries = []
        for task_name, suite_source in sorted(train_suite_map.items()):
            entries.append(
                {
                    "name": str(task_name),
                    "status": "complete",
                    "train_suite_source": str(suite_source),
                }
            )
        return entries

    task_name = str(example["task_name"])
    suite_source = str(example["train_suite_source"])
    return [
        {
            "name": task_name,
            "status": "complete",
            "train_suite_source": suite_source,
        }
    ]


def _target_files_for_example(objective: ParsedObjective, unit_kind: str) -> list[str]:
    """Resolve minimal implementation files needed for isolated evaluation.

    Args:
        objective: Parsed objective data for the current run.
        unit_kind: Verifier unit kind (`task` or `objective`).

    Returns:
        Ordered target file list for isolated evaluation.
    """
    targets: list[str] = list(objective.target_files)
    if unit_kind == _OBJECTIVE_KEY:
        for task in objective.tasks:
            for path in task.target_files:
                if path not in targets:
                    targets.append(path)
    return targets


def _resolve_profiles_path(workspace: Path, profiles_path: Path | None) -> Path:
    """Resolve profiles path relative to workspace when needed.

    Args:
        workspace: Workspace root directory.
        profiles_path: Optional path from CLI/runtime context.

    Returns:
        Absolute path for the profiles file.
    """
    if profiles_path is None:
        return (workspace / "constraints" / "profiles.yaml").resolve()
    if profiles_path.is_absolute():
        return profiles_path.resolve()
    return (workspace / profiles_path).resolve()


def _prepare_profiles_path_for_isolated_workspace(
    source_workspace: Path,
    destination_workspace: Path,
    profiles_path: Path,
) -> Path:
    """Prepare profiles path for isolated black-box execution.

    Args:
        source_workspace: Source workspace containing objective/config files.
        destination_workspace: Temporary destination workspace used for evaluation.
        profiles_path: Resolved profiles path for this run.

    Returns:
        Profiles path that should be passed to the isolated evaluation step.
    """
    resolved_source = source_workspace.resolve()
    resolved_profiles = profiles_path.resolve()
    try:
        relative = resolved_profiles.relative_to(resolved_source)
    except ValueError:
        return resolved_profiles

    destination_profiles = destination_workspace / relative
    if resolved_profiles.exists():
        _copy_file(resolved_profiles, destination_profiles)
    return destination_profiles


def _prepare_isolated_workspace(
    source_workspace: Path,
    destination_workspace: Path,
    target_files: list[str],
) -> None:
    """Create isolated workspace copy for one-example black-box execution.

    Args:
        source_workspace: Source workspace containing implementation files.
        destination_workspace: Temporary destination workspace used for evaluation.
        target_files: Repo-relative Python files requested by objective/task scope.
    """
    (destination_workspace / "src").mkdir(parents=True, exist_ok=True)
    (destination_workspace / "tests").mkdir(parents=True, exist_ok=True)

    for rel_root in _copy_roots_for_targets(target_files):
        src = source_workspace / rel_root
        dst = destination_workspace / rel_root
        if not src.exists():
            continue
        if src.is_dir():
            shutil.copytree(
                src,
                dst,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(*_COPYTREE_IGNORES),
            )
            continue
        _copy_file(src, dst)

    _copy_root_python_siblings_if_needed(
        source_workspace=source_workspace,
        destination_workspace=destination_workspace,
        target_files=target_files,
    )
    _copy_project_config_files(source_workspace, destination_workspace)


def _copy_roots_for_targets(target_files: list[str]) -> list[Path]:
    """Resolve top-level roots that should be copied for evaluation context.

    Args:
        target_files: Repo-relative Python files requested by objective/task scope.

    Returns:
        Ordered list of root paths to copy from source workspace.
    """
    roots: list[Path] = []
    for rel_path in target_files:
        path = Path(rel_path)
        if path.is_absolute() or not path.parts:
            continue

        root = Path(path.parts[0]) if len(path.parts) > 1 else path
        if root not in roots:
            roots.append(root)
    return roots


def _copy_root_python_siblings_if_needed(
    source_workspace: Path,
    destination_workspace: Path,
    target_files: list[str],
) -> None:
    """Copy top-level Python siblings for root-level target files.

    Args:
        source_workspace: Source workspace containing implementation files.
        destination_workspace: Temporary destination workspace used for evaluation.
        target_files: Repo-relative Python files requested by objective/task scope.
    """
    has_root_level_python_target = False
    for rel_path in target_files:
        path = Path(rel_path)
        if not path.is_absolute() and len(path.parts) == 1 and path.suffix == ".py":
            has_root_level_python_target = True
            break

    if not has_root_level_python_target:
        return

    for source_file in source_workspace.glob("*.py"):
        if not source_file.is_file():
            continue
        _copy_file(source_file, destination_workspace / source_file.name)


def _copy_project_config_files(source_workspace: Path, destination_workspace: Path) -> None:
    """Copy common project config files used by pytest/import resolution.

    Args:
        source_workspace: Source workspace containing implementation files.
        destination_workspace: Temporary destination workspace used for evaluation.
    """
    for filename in _PROJECT_CONFIG_FILES:
        src = source_workspace / filename
        if not src.exists() or not src.is_file():
            continue
        _copy_file(src, destination_workspace / filename)


def _copy_file(src: Path, dst: Path) -> None:
    """Copy one file into destination workspace, creating parent directories.

    Args:
        src: Existing source file path.
        dst: Destination file path in isolated workspace.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _should_promote(
    baseline: AggregatedMetrics,
    candidate: AggregatedMetrics,
    min_score_delta: float,
) -> bool:
    """Apply promotion gate: val-score improvement with no correctness regression.

    Args:
        baseline: Baseline validation metrics for active policy.
        candidate: Candidate policy dictionary under evaluation.
        min_score_delta: Minimum required validation score improvement for promotion.

    Returns:
        True when the operation succeeds; otherwise False.
    """
    return (
        candidate.mean_final_score >= baseline.mean_final_score + min_score_delta
        and candidate.mean_correctness >= baseline.mean_correctness
    )


def _build_run_report(outcome: dict[str, Any]) -> str:
    """Render a markdown report for one optimizer run.

    Args:
        outcome: Value for `outcome` used by `_build_run_report`.

    Returns:
        Computed text result for this operation.
    """
    lines = [
        "# Crucis Optimizer Run",
        "",
        f"- state: {outcome.get('state')}",
        f"- job_id: {outcome.get('job_id')}",
        f"- trigger: {outcome.get('trigger')}",
        f"- promoted: {outcome.get('promoted')}",
        f"- candidate_ready: {outcome.get('candidate_ready')}",
        f"- candidate_run_id: {outcome.get('candidate_run_id')}",
        f"- message: {outcome.get('message')}",
        "",
    ]

    baseline = outcome.get("baseline") or {}
    candidate = outcome.get("candidate") or {}
    if baseline or candidate:
        lines.extend(
            [
                "## Validation Metrics",
                "",
                "| policy | mean_final_score | mean_correctness | mean_speed | examples |",
                "|---|---:|---:|---:|---:|",
                "| baseline | "
                f"{baseline.get(_MEAN_FINAL_SCORE_KEY, 0):.4f} | "
                f"{baseline.get('mean_correctness', 0):.4f} | "
                f"{baseline.get('mean_speed', 0):.4f} | "
                f"{baseline.get('num_examples', 0)} |",
                "| candidate | "
                f"{candidate.get(_MEAN_FINAL_SCORE_KEY, 0):.4f} | "
                f"{candidate.get('mean_correctness', 0):.4f} | "
                f"{candidate.get('mean_speed', 0):.4f} | "
                f"{candidate.get('num_examples', 0)} |",
                "",
            ]
        )
    return "\n".join(lines)


def _classify_failure(returncode: int, stdout: str, stderr: str) -> str:
    """Classify failure category from subprocess outputs.

    Args:
        returncode: Value for `returncode` used by `_classify_failure`.
        stdout: Process stdout text.
        stderr: Process stderr text.

    Returns:
        Computed text result for this operation.
    """
    text = f"{stdout}\n{stderr}".lower()
    if returncode == 0:
        return "ok"
    if returncode == -1 or "timed out" in text:
        return "timeout"
    if "agent failed" in text or "binary not found" in text:
        return "agent_failure"
    if "holdout" in text:
        return "holdout_failure"
    if "no checkpoint" in text:
        return "checkpoint_error"
    return "test_failure"


def _bounded_excerpt(text: str, limit: int) -> str:
    """Trim text excerpt to a fixed maximum length.

    Args:
        text: Input text to transform or truncate.
        limit: Maximum number of characters to keep.

    Returns:
        Computed text result for this operation.
    """
    clean = (text or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[:limit] + "\n...[truncated]..."


def _utc_now() -> str:
    """utc now.

    Returns:
        Computed text result for this operation.
    """
    return datetime.now(UTC).isoformat()


def _acquire_worker_lock(workspace: Path) -> bool:
    """Acquire exclusive worker lock; return False when already locked.

    Args:
        workspace: Workspace root directory.

    Returns:
        True when the operation succeeds; otherwise False.
    """
    path = lock_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)

    if _try_create_lock_file(path):
        return True

    if _is_stale_lock(path):
        path.unlink(missing_ok=True)
        return _try_create_lock_file(path)
    return False


def _release_worker_lock(workspace: Path) -> None:
    """Release exclusive worker lock.

    Args:
        workspace: Workspace root directory.
    """
    lock_path(workspace).unlink(missing_ok=True)


def _try_create_lock_file(path: Path) -> bool:
    """Create a worker lock file atomically.

    Args:
        path: Path to worker lock file.

    Returns:
        True when lock creation succeeds.
    """
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(path, flags)
    except FileExistsError:
        return False

    payload = {"pid": os.getpid(), "created_at": _utc_now()}
    with os.fdopen(fd, "w", encoding=TEXT_ENCODING) as handle:
        handle.write(json.dumps(payload))
    return True


def _is_stale_lock(path: Path) -> bool:
    """Return True when lock file is stale and safe to recover.

    Args:
        path: Path to worker lock file.

    Returns:
        True when stale lock recovery should occur.
    """
    payload = _load_lock_payload(path)
    if payload is None:
        return True

    pid = payload.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return True

    created_at = payload.get("created_at")
    age_seconds = _lock_age_seconds(created_at)
    if age_seconds is not None and age_seconds > LOCK_STALE_MAX_AGE_SEC:
        return True

    if not _pid_is_alive(pid):
        return True

    command = _pid_command_line(pid)
    if command:
        return not _is_optimizer_worker_command(command)

    # If command lookup is unavailable, avoid stealing a live lock unless it is clearly stale.
    return age_seconds is not None and age_seconds > LOCK_STALE_MAX_AGE_SEC


def _load_lock_payload(path: Path) -> dict[str, Any] | None:
    """Load lock payload from JSON or legacy plain PID format.

    Args:
        path: Path to worker lock file.

    Returns:
        Payload with pid and created_at when parseable, else None.
    """
    try:
        raw = path.read_text(encoding=TEXT_ENCODING).strip()
    except OSError:
        return None
    if not raw:
        return None

    try:
        loaded = json.loads(raw)
        if isinstance(loaded, dict):
            return loaded
    except json.JSONDecodeError:
        pass

    try:
        legacy_pid = int(raw)
    except ValueError:
        return None
    return {"pid": legacy_pid, "created_at": None}


def _pid_is_alive(pid: int) -> bool:
    """Return True when PID is currently running.

    Args:
        pid: Process ID from lock payload.

    Returns:
        True when process exists.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _pid_command_line(pid: int) -> str | None:
    """Best-effort lookup of process command line for lock ownership checks.

    Args:
        pid: Process ID from lock payload.

    Returns:
        Full command line string when available; otherwise None.
    """
    proc_cmdline = Path("/proc") / str(pid) / "cmdline"
    if proc_cmdline.exists():
        try:
            raw = proc_cmdline.read_bytes()
        except OSError:
            raw = b""
        command = raw.replace(b"\x00", b" ").decode(TEXT_ENCODING, errors="replace").strip()
        if command:
            return command

    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None

    command = (completed.stdout or "").strip()
    return command or None


def _is_optimizer_worker_command(command: str) -> bool:
    """Return True when command line belongs to Crucis optimizer worker.

    Args:
        command: Full command line text.

    Returns:
        True when command appears to be a Crucis GEPA worker process.
    """
    normalized = command.lower()
    return _WORKER_CMD_MARKER in normalized


def _lock_age_seconds(created_at: object) -> float | None:
    """Parse lock timestamp and return age in seconds.

    Args:
        created_at: Timestamp value from lock payload.

    Returns:
        Age in seconds when parseable; otherwise None.
    """
    if not isinstance(created_at, str) or not created_at.strip():
        return None
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)

    age = (datetime.now(UTC) - created).total_seconds()
    return max(age, 0.0)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the background optimizer worker.

    Args:
        argv: Optional CLI arguments; defaults to process arguments when None.

    Returns:
        Result of `main`.
    """
    parser = argparse.ArgumentParser(prog="crucis-gepa-optimizer")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--once", action="store_true", default=False)
    args = parser.parse_args(argv)
    return run_optimizer_worker(Path(args.workspace), once=bool(args.once))


if __name__ == "__main__":
    raise SystemExit(main())
