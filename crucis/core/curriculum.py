"""Generate an evaluation curriculum from checkpoint state and objective."""

from __future__ import annotations

import logging
from pathlib import Path

from crucis.defaults import TEXT_ENCODING
from crucis.models import CheckpointState, ParsedObjective, TaskConstraints, TrainingStatus

_log = logging.getLogger(__name__)

_MAX_CONTEXT_LINES = 500


def _prepare_constraints_data(
    constraints_map: dict[str, TaskConstraints],
) -> dict[str, dict]:
    """Pre-compute constraint model dumps for template rendering.

    Args:
        constraints_map: Mapping of task names to resolved constraints.

    Returns:
        Dict keyed by task name with primary_dump, secondary_dump, and guidance.
    """
    result = {}
    for name, constraints in constraints_map.items():
        result[name] = {
            "primary_dump": constraints.primary.model_dump(exclude_none=True),
            "secondary_dump": constraints.secondary.model_dump(exclude_none=True),
            "guidance": constraints.guidance,
        }
    return result


def read_context_files(
    workspace: Path,
    paths: list[str],
    max_lines: int = _MAX_CONTEXT_LINES,
) -> dict[str, str]:
    """Read workspace files and return their contents keyed by relative path.

    Skips files that don't exist. Truncates files exceeding *max_lines*.

    Args:
        workspace: Workspace root directory.
        paths: Workspace-relative file paths to read.
        max_lines: Maximum lines per file before truncation.

    Returns:
        Dict mapping relative path to file contents.
    """
    result: dict[str, str] = {}
    for rel_path in paths:
        full = workspace / rel_path
        if not full.exists():
            _log.warning("context file not found, skipping: %s", rel_path)
            continue
        try:
            lines = full.read_text(encoding=TEXT_ENCODING).splitlines()
        except (OSError, UnicodeDecodeError):
            _log.warning("could not read context file: %s", rel_path)
            continue
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines.append(f"[truncated at {max_lines} lines]")
        result[rel_path] = "\n".join(lines)
    return result


def build_curriculum(
    state: CheckpointState,
    objective: ParsedObjective,
    constraints_map: dict[str, TaskConstraints],
    implementation_constraints_map: dict[str, TaskConstraints] | None = None,
    workspace: Path | None = None,
) -> str:
    """Build a structured markdown curriculum for the evaluation agent.

    Args:
        state: Checkpoint state being processed.
        objective: Parsed objective data for the current run.
        constraints_map: Mapping of task names to resolved test constraints.
        implementation_constraints_map: Mapping of task names to resolved implementation constraints.
        workspace: Workspace root for reading context and target files.

    Returns:
        Computed text result for this operation.
    """
    from crucis.prompts import render

    completed = [p for p in state.task_progress if p.status == TrainingStatus.complete]
    task_lookup = {task.name: task for task in objective.tasks}
    test_cd = _prepare_constraints_data(constraints_map)
    impl_cd = _prepare_constraints_data(implementation_constraints_map) if implementation_constraints_map else None

    context_files_content: dict[str, str] = {}
    target_files_content: dict[str, str] = {}
    if workspace is not None:
        all_context = list(objective.context_files)
        for task in objective.tasks:
            all_context.extend(task.context_files)
        context_files_content = read_context_files(workspace, all_context)
        target_files_content = read_context_files(workspace, objective.target_files)

    return render(
        "curriculum.jinja2",
        objective=objective,
        completed_tasks=completed,
        task_lookup=task_lookup,
        test_constraints=test_cd,
        impl_constraints=impl_cd,
        context_files_content=context_files_content,
        target_files_content=target_files_content,
    )


def write_curriculum_to_workspace(curriculum_content: str, workspace: Path) -> Path:
    """Write curriculum text to ``curriculum.md`` inside workspace.

    Args:
        curriculum_content: Value for `curriculum_content` used by `write_curriculum_to_workspace`.
        workspace: Workspace root directory.

    Returns:
        Resolved filesystem path for this operation.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    curriculum_path = workspace / "curriculum.md"
    curriculum_path.write_text(curriculum_content, encoding=TEXT_ENCODING)
    return curriculum_path
