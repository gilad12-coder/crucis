"""Generation plan builder for structured test-suite guidance."""

from __future__ import annotations

import time
from pathlib import Path

from crucis.cli.runner import run_cli_agent
from crucis.config import Config
from crucis.defaults import TEXT_ENCODING
from crucis.models import ParsedObjective, TaskConstraints
from crucis.persistence.audit import log_agent_call
from crucis.persistence.events import EventLogger

_PLAN_FILENAME = "plan.md"


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


def build_plan_prompt(
    objective: ParsedObjective,
    constraints_map: dict[str, TaskConstraints],
) -> str:
    """Build a meta-prompt that instructs an agent to write a generation plan.

    Args:
        objective: Parsed objective data for the current run.
        constraints_map: Mapping of task names to resolved constraints.

    Returns:
        Prompt text for the planning agent.
    """
    from crucis.prompts import render

    effective_tasks = objective.tasks or [objective]
    return render(
        "plan.jinja2",
        objective=objective,
        effective_tasks=effective_tasks,
        constraints_data=_prepare_constraints_data(constraints_map),
    )


def build_generation_plan(
    objective: ParsedObjective,
    constraints_map: dict[str, TaskConstraints],
    config: Config,
    logger: EventLogger | None = None,
) -> str:
    """Call an agent to generate a structured plan for test-suite generation.

    Args:
        objective: Parsed objective data for the current run.
        constraints_map: Mapping of task names to resolved constraints.
        config: Runtime configuration values.
        logger: Optional event logger for audit trail.

    Returns:
        Generated plan content as markdown text.
    """
    prompt = build_plan_prompt(objective, constraints_map)
    t0 = time.monotonic()
    result = run_cli_agent(
        prompt,
        config.generation_agent,
        config.generation_model,
        config.max_budget_usd,
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
        call_site="build_generation_plan",
        task=objective.name,
    )
    if result.exit_code != 0:
        raise RuntimeError(f"Plan generation failed: {result.stderr}")
    return _extract_markdown(result.stdout)


def _extract_markdown(text: str) -> str:
    """Extract markdown content, stripping optional fences.

    Args:
        text: Raw agent response text.

    Returns:
        Cleaned markdown content.
    """
    stripped = text.strip()
    if stripped.startswith("```markdown") or stripped.startswith("```md"):
        newline_pos = stripped.find("\n")
        if newline_pos == -1:
            return ""
        stripped = stripped[newline_pos + 1 :]
    if stripped.startswith("```"):
        stripped = stripped[3:].lstrip("\n")
    if stripped.endswith("```"):
        stripped = stripped[:-3].rstrip()
    return stripped


def write_plan_to_workspace(plan_content: str, workspace: Path) -> Path:
    """Write plan markdown to the workspace root.

    Args:
        plan_content: Generated plan markdown text.
        workspace: Workspace root directory.

    Returns:
        Path to the written plan file.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    plan_path = workspace / _PLAN_FILENAME
    plan_path.write_text(plan_content, encoding=TEXT_ENCODING)
    return plan_path


def load_plan(workspace: Path) -> str | None:
    """Load plan.md from workspace if it exists.

    Args:
        workspace: Workspace root directory.

    Returns:
        Plan content or None if no plan file exists.
    """
    plan_path = workspace / _PLAN_FILENAME
    if not plan_path.exists():
        return None
    return plan_path.read_text(encoding=TEXT_ENCODING)
