"""Shared helpers used by loop.py and evaluation.py.

Extracted to break the circular dependency between these modules.
"""

from pathlib import Path

from crucis.config import Config
from crucis.diagnostics import collect_preflight_checks
from crucis.display import display_error, display_info
from crucis.execution.optimizer import enqueue_background_optimization
from crucis.models import CheckpointState, ParsedObjective
from crucis.persistence.events import EventLogger


class PreflightError(RuntimeError):
    """Raised when preflight diagnostics detect a blocking failure."""


def _run_preflight(workspace: Path, config: Config, phase: str) -> None:
    """Run preflight diagnostics and abort on hard failures.

    Args:
        workspace: Workspace root directory.
        config: Runtime configuration values.
        phase: Phase name for error messages (fit/evaluate).
    """
    agents = [config.generation_agent, config.critic_agent, config.implementation_agent]
    checks = collect_preflight_checks(
        workspace=workspace,
        config=config,
        required_agents=agents,
        require_pytest=True,
    )
    failures = [c for c in checks if c.status == "fail"]
    if not failures:
        return
    messages = [f"  - {c.message}" for c in failures]
    hint = failures[0].hint or ""
    detail = "\n".join(messages)
    raise PreflightError(f"Preflight failed before {phase}:\n{detail}\n{hint}")


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
        display_info(f"Run log: {logger.path}")
    return logger
