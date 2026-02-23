"""Checkpoint state creation and persistence helpers."""

from pathlib import Path

from pydantic import ValidationError

from crucis.defaults import TEXT_ENCODING
from crucis.models import CheckpointState, ParsedObjective, TaskProgress


def create_checkpoint(objective: ParsedObjective) -> CheckpointState:
    """Create initial checkpoint state from a parsed objective.

    Args:
        objective: Parsed objective data for the current run.

    Returns:
        Created object or state.
    """
    if objective.tasks:
        progress = [TaskProgress(name=task.name) for task in objective.tasks]
    else:
        progress = [TaskProgress(name=objective.name)]
    return CheckpointState(task_progress=progress)


def save_checkpoint(state: CheckpointState, path: Path) -> None:
    """Persist checkpoint state to disk as JSON.

    Args:
        state: Checkpoint state being processed.
        path: Filesystem path used by the current operation.
    """
    path.write_text(state.model_dump_json(indent=2), encoding=TEXT_ENCODING)


def load_checkpoint(path: Path) -> CheckpointState | None:
    """Load checkpoint state from disk, returning None if absent.

    Args:
        path: Filesystem path used by the current operation.

    Returns:
        None.
    """
    if not path.exists():
        return None
    try:
        return CheckpointState.model_validate_json(path.read_text(encoding=TEXT_ENCODING))
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise ValueError(f"Invalid checkpoint file {path}: {errors}") from None
