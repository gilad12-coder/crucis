"""Crucis MCP server — full CLI parity + step-by-step agent mode."""

from __future__ import annotations

import asyncio
import io
import json
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from crucis.mcp._workspace import (
    InputTooLargeError,
    PathTraversalError,
    WorkspaceContext,
    WorkspaceNotAuthorizedError,
    check_workspace_authorized,
    resolve_workspace,
    safe_resolve_path,
    validate_source_input,
)

# ---------------------------------------------------------------------------
# FastMCP instance
# ---------------------------------------------------------------------------

_INSTRUCTIONS = (
    "Crucis is a verification-first TDD pipeline. Use these tools to scaffold "
    "workspaces, validate objectives, generate and harden test suites, check "
    "code against constraints, run the full pipeline, and verify implementations. "
    "Two modes: (1) pipeline mode — Crucis spawns agents automatically, "
    "(2) step-by-step mode — you act as generator/critic/implementer using "
    "get_prompt, submit, and verify tools."
)


@asynccontextmanager
async def _lifespan(server: FastMCP):
    """Initialize workspace context for the server lifetime."""
    ctx = WorkspaceContext(workspace=resolve_workspace())
    yield ctx


mcp = FastMCP("Crucis", instructions=_INSTRUCTIONS, lifespan=_lifespan)


# ---------------------------------------------------------------------------
# Tool annotations
# ---------------------------------------------------------------------------

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False)
_MUTATING = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
_DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True)
_LLM_CALL = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _suppress_stdout():
    """Redirect stdout to prevent Rich output from corrupting STDIO JSON-RPC."""
    sys.stdout = io.StringIO()


def _restore_stdout(original):
    """Restore original stdout."""
    sys.stdout = original


def _error(exc: Exception, *, hint: str = "") -> dict:
    """Build a structured error response with type info and actionable hint."""
    resp = {"error": str(exc), "error_type": type(exc).__name__}
    if hint:
        resp["hint"] = hint
    return resp


def _build_task_objective(task_name: str, objective):
    """Extract a single-task objective from a multi-task objective.

    Returns the original objective unchanged when task_name is None or
    not found in the task list.
    """
    if not task_name or not objective.tasks:
        return objective
    for t in objective.tasks:
        if t.name == task_name:
            from crucis.models import ParsedObjective
            return ParsedObjective(
                name=t.name,
                description=t.description or objective.description,
                train_evals=list(t.train_evals or objective.train_evals),
                holdout_evals=list(t.holdout_evals or objective.holdout_evals),
                signature=t.signature or objective.signature,
                target_files=list(t.target_files or objective.target_files),
                tasks=list(objective.tasks),
                verification_granularity=objective.verification_granularity,
            )
    return objective


def _pre_validate(ctx: WorkspaceContext, obj_path: Path, prof_path: Path) -> str | None:
    """Quick pre-flight check before long-running operations.

    Returns an error message if something is wrong, None if OK.
    """
    from crucis.constraints.loader import load_profiles
    from crucis.intake.objective import parse_objective

    try:
        objective = parse_objective(obj_path)
    except (ValueError, FileNotFoundError) as exc:
        return f"Objective validation failed: {exc}"

    try:
        profiles = load_profiles(prof_path)
    except (ValueError, FileNotFoundError) as exc:
        return f"Profiles validation failed: {exc}"

    # Check that referenced constraint profiles exist
    profile_name = objective.tests_constraint_profile or "default"
    if profile_name not in profiles:
        available = [k for k in profiles if k != "tasks"]
        return (
            f"Constraint profile '{profile_name}' not found in {prof_path}. "
            f"Available: {available}"
        )
    return None


def _ctx(workspace: str | None = None) -> WorkspaceContext:
    """Build a WorkspaceContext from an optional override.

    Enforces workspace authorization on every tool call.
    """
    ws = resolve_workspace(workspace)
    check_workspace_authorized(ws)
    return WorkspaceContext(workspace=ws)


def _ensure_settings(ws: Path) -> None:
    """Load runtime settings and apply agent config to env."""
    from crucis.persistence.settings import apply_agent_settings_to_env, try_load_runtime_settings

    settings = try_load_runtime_settings(ws)
    if settings is not None:
        apply_agent_settings_to_env(settings)


def _checkpoint_payload(state, checkpoint_path: Path, optimizer_status) -> dict:
    """Build machine-readable checkpoint summary."""
    complete_count = sum(
        1 for p in state.task_progress if p.status.value == "complete"
    )
    total_count = len(state.task_progress)
    tasks = []
    for p in state.task_progress:
        tasks.append({
            "name": p.name,
            "status": p.status.value,
            "has_train_suite": bool(p.train_suite_source),
            "has_adversarial_report": p.adversarial_report is not None,
        })
    return {
        "checkpoint_path": str(checkpoint_path),
        "workspace": str(checkpoint_path.parent),
        "summary": {
            "total_tasks": total_count,
            "complete_tasks": complete_count,
            "evaluation_passed": state.evaluation_passed,
            "ready_for_evaluation": total_count > 0 and complete_count == total_count,
        },
        "tasks": tasks,
        "optimizer_status": (
            optimizer_status.model_dump(mode="json") if optimizer_status is not None else None
        ),
    }


# ===================================================================
# PART A: Pipeline Tools (13) — Full CLI Parity
# ===================================================================


@mcp.tool(annotations=_MUTATING)
async def crucis_init(
    name: str = "my_project",
    existing_codebase: bool = False,
    workspace: str | None = None,
) -> dict:
    """Scaffold a new Crucis workspace with starter files.

    Creates objective.yaml, constraints/profiles.yaml, and .crucis/settings.yaml.
    Skips files that already exist. Use this as the first step when starting a new
    Crucis project. Do NOT use if objective.yaml already exists — edit it directly instead.

    Args:
        name: Project name for the objective template.
        existing_codebase: Treat workspace as an existing codebase.
        workspace: Directory to scaffold. Defaults to CRUCIS_WORKSPACE or cwd.
    """
    from crucis.intake.scaffold import detect_existing_codebase, scaffold_workspace

    try:
        ws = resolve_workspace(workspace)
        check_workspace_authorized(ws)
        if not existing_codebase:
            existing_codebase = detect_existing_codebase(ws)
        created = scaffold_workspace(ws, name=name, existing_codebase=existing_codebase)
        return {
            "workspace": str(ws),
            "created": [str(p) for p in created],
            "existing_codebase": existing_codebase,
            "next_steps": [
                "Edit objective.yaml to define your function, evals, and target files",
                "Run crucis_validate to check the objective",
                "Run crucis_doctor to verify environment prerequisites",
            ],
        }
    except Exception as exc:
        return _error(exc, hint="Check that the workspace directory exists and is writable.")


@mcp.tool(annotations=_LLM_CALL)
async def crucis_run(
    objective_path: str | None = None,
    task_names: list[str] | None = None,
    no_sandbox: bool = True,
    profiles: str | None = None,
    checkpoint: str | None = None,
    workspace: str | None = None,
) -> dict:
    """Run the complete Crucis pipeline: fit (generate+harden tests) then evaluate (implement+verify).

    Long-running — spawns subprocess agents for generation, adversarial review, and
    implementation. Pre-validates objective and profiles before starting. Use crucis_dry_run
    first to preview prompts without API calls.

    Args:
        objective_path: Path to objective YAML. Defaults to objective.yaml in workspace.
        task_names: Optional list of specific task names to process.
        no_sandbox: Skip Docker sandbox, run pytest on host (default: true).
        profiles: Path to constraint profiles YAML.
        checkpoint: Path to checkpoint JSON.
        workspace: Workspace directory root.
    """
    from crucis.core.loop import run_fit
    from crucis.persistence.policy import load_optimizer_status

    try:
        ctx = _ctx(workspace)
        _ensure_settings(ctx.workspace)
        obj_path = safe_resolve_path(objective_path, ctx.objective_path, ctx.workspace)
        prof_path = safe_resolve_path(profiles, ctx.profiles_path, ctx.workspace)
        ckpt_path = safe_resolve_path(checkpoint, ctx.checkpoint_path, ctx.workspace)

        # Pre-validate before starting the long pipeline
        preflight_err = _pre_validate(ctx, obj_path, prof_path)
        if preflight_err:
            return _error(ValueError(preflight_err), hint="Fix the issue and retry.")

        loop = asyncio.get_event_loop()
        state = await loop.run_in_executor(None, lambda: run_fit(
            objective_path=obj_path,
            profiles_path=prof_path,
            checkpoint_path=ckpt_path,
            auto_tests=True,
            auto_adversary=True,
            auto_evaluate=True,
            workspace=ctx.workspace,
            no_sandbox=no_sandbox,
            task_names=task_names,
        ))

        opt_status = load_optimizer_status(ctx.workspace)
        payload = _checkpoint_payload(state, ckpt_path, opt_status)
        if state.evaluation_passed:
            payload["next_steps"] = [
                "Use crucis_summary to review detailed per-task results",
            ]
        else:
            payload["next_steps"] = [
                "Use crucis_summary with task_name to inspect failing tasks",
                "Use crucis_reset with task_names to retry specific tasks",
            ]
        return payload
    except (PathTraversalError, WorkspaceNotAuthorizedError) as exc:
        return _error(exc)
    except Exception as exc:
        return _error(exc)


@mcp.tool(annotations=_LLM_CALL)
async def crucis_run_fit(
    objective_path: str | None = None,
    task_names: list[str] | None = None,
    profiles: str | None = None,
    checkpoint: str | None = None,
    workspace: str | None = None,
) -> dict:
    """Run the FIT phase only: generate test suites and harden them adversarially.

    Long-running — spawns agents. Generates pytest suites, validates constraints,
    runs adversarial review and cheating probes. Does NOT implement code.
    Use crucis_run_evaluate afterwards to implement and verify.

    Args:
        objective_path: Path to objective YAML.
        task_names: Optional list of specific task names to process.
        profiles: Path to constraint profiles YAML.
        checkpoint: Path to checkpoint JSON.
        workspace: Workspace directory root.
    """
    from crucis.core.loop import run_fit
    from crucis.persistence.policy import load_optimizer_status

    try:
        ctx = _ctx(workspace)
        _ensure_settings(ctx.workspace)
        obj_path = safe_resolve_path(objective_path, ctx.objective_path, ctx.workspace)
        prof_path = safe_resolve_path(profiles, ctx.profiles_path, ctx.workspace)
        ckpt_path = safe_resolve_path(checkpoint, ctx.checkpoint_path, ctx.workspace)

        preflight_err = _pre_validate(ctx, obj_path, prof_path)
        if preflight_err:
            return _error(ValueError(preflight_err), hint="Fix the issue and retry.")

        loop = asyncio.get_event_loop()
        state = await loop.run_in_executor(None, lambda: run_fit(
            objective_path=obj_path,
            profiles_path=prof_path,
            checkpoint_path=ckpt_path,
            auto_tests=True,
            auto_adversary=True,
            auto_evaluate=False,
            workspace=ctx.workspace,
            task_names=task_names,
        ))

        opt_status = load_optimizer_status(ctx.workspace)
        payload = _checkpoint_payload(state, ckpt_path, opt_status)
        payload["next_steps"] = [
            "Use crucis_summary to review adversarial reports",
            "Use crucis_run_evaluate to implement and verify code",
        ]
        return payload
    except (PathTraversalError, WorkspaceNotAuthorizedError) as exc:
        return _error(exc)
    except Exception as exc:
        return _error(exc)


@mcp.tool(annotations=_LLM_CALL)
async def crucis_run_evaluate(
    objective_path: str | None = None,
    no_sandbox: bool = True,
    profiles: str | None = None,
    checkpoint: str | None = None,
    workspace: str | None = None,
) -> dict:
    """Run the EVALUATE phase: implement code and verify it passes tests + holdout evals.

    Requires FIT phase to be complete (all tasks must have test suites). Builds a
    curriculum, dispatches an implementation agent, then verifies. Do NOT use before
    crucis_run_fit — use crucis_summary to check readiness.

    Args:
        objective_path: Path to objective YAML.
        no_sandbox: Skip Docker sandbox, run pytest on host (default: true).
        profiles: Path to constraint profiles YAML.
        checkpoint: Path to checkpoint JSON.
        workspace: Workspace directory root.
    """
    from crucis.config import Config
    from crucis.constraints.loader import load_profiles, resolve_constraints
    from crucis.core.loop import run_evaluation
    from crucis.execution.sandbox import check_docker_available
    from crucis.intake.objective import parse_objective
    from crucis.persistence.checkpoint import load_checkpoint, save_checkpoint
    from crucis.persistence.policy import load_optimizer_status

    try:
        ctx = _ctx(workspace)
        _ensure_settings(ctx.workspace)
        obj_path = safe_resolve_path(objective_path, ctx.objective_path, ctx.workspace)
        prof_path = safe_resolve_path(profiles, ctx.profiles_path, ctx.workspace)
        ckpt_path = safe_resolve_path(checkpoint, ctx.checkpoint_path, ctx.workspace)

        objective = parse_objective(obj_path)
        state = load_checkpoint(ckpt_path)
        if state is None:
            return {"error": f"No checkpoint found at {ckpt_path}.", "hint": "Run crucis_run_fit first to generate test suites."}

        profiles_data = load_profiles(prof_path)
        config = Config()
        use_sandbox = not no_sandbox
        if use_sandbox and not check_docker_available():
            use_sandbox = False

        constraints_map = {
            p.name: resolve_constraints(objective, profiles_data, p.name, scope="tests")
            for p in state.task_progress
        }
        impl_constraints_map = {
            p.name: resolve_constraints(objective, profiles_data, p.name, scope="implementation")
            for p in state.task_progress
        }

        loop = asyncio.get_event_loop()
        passed = await loop.run_in_executor(None, lambda: run_evaluation(
            state, config,
            test_dir=ctx.workspace / "tests",
            objective=objective,
            constraints_map=constraints_map,
            implementation_constraints_map=impl_constraints_map,
            use_sandbox=use_sandbox,
            profiles_path=prof_path,
        ))

        if passed:
            state.evaluation_passed = True
            save_checkpoint(state, ckpt_path)

        complete = sum(1 for p in state.task_progress if p.status.value == "complete")
        result = {
            "passed": passed,
            "tasks_completed": complete,
            "tasks_total": len(state.task_progress),
        }
        if passed:
            result["next_steps"] = ["All tasks passed. Implementation is verified."]
        else:
            result["next_steps"] = [
                "Use crucis_summary with task_name to inspect failures",
                "Fix the objective or implementation and re-run",
            ]
        return result
    except (PathTraversalError, WorkspaceNotAuthorizedError) as exc:
        return _error(exc)
    except Exception as exc:
        return _error(exc)


@mcp.tool(annotations=_LLM_CALL)
async def crucis_run_plan(
    objective_path: str | None = None,
    force: bool = False,
    profiles: str | None = None,
    workspace: str | None = None,
) -> dict:
    """Generate a structured plan.md for test-suite generation strategy.

    Calls an LLM to build a plan that guides subsequent test generation. The plan
    is saved to plan.md in the workspace. Set force=true to regenerate an existing plan.

    Args:
        objective_path: Path to objective YAML.
        force: Regenerate plan even if plan.md already exists.
        profiles: Path to constraint profiles YAML.
        workspace: Workspace directory root.
    """
    from crucis.config import Config
    from crucis.constraints.loader import load_profiles, resolve_constraints
    from crucis.core.planner import build_generation_plan, write_plan_to_workspace
    from crucis.intake.objective import parse_objective

    try:
        ctx = _ctx(workspace)
        _ensure_settings(ctx.workspace)
        obj_path = safe_resolve_path(objective_path, ctx.objective_path, ctx.workspace)
        prof_path = safe_resolve_path(profiles, ctx.profiles_path, ctx.workspace)

        plan_path = ctx.workspace / "plan.md"
        if plan_path.exists() and not force:
            return {"error": f"Plan already exists at {plan_path}. Set force=true to regenerate."}

        objective = parse_objective(obj_path)
        profiles_data = load_profiles(prof_path)
        effective_tasks = objective.tasks or [objective]
        constraints_map = {
            task.name: resolve_constraints(objective, profiles_data, task.name)
            for task in effective_tasks
        }

        config = Config()
        loop = asyncio.get_event_loop()
        plan_content = await loop.run_in_executor(
            None, lambda: build_generation_plan(objective, constraints_map, config)
        )
        created = write_plan_to_workspace(plan_content, ctx.workspace)
        return {
            "plan_path": str(created),
            "content": plan_content,
            "next_steps": [
                "Review the plan, then run crucis_run or crucis_run_fit to execute",
            ],
        }
    except Exception as exc:
        return _error(exc)


@mcp.tool(annotations=_READ_ONLY)
async def crucis_dry_run(
    objective_path: str | None = None,
    task_names: list[str] | None = None,
    profiles: str | None = None,
    workspace: str | None = None,
) -> dict:
    """Preview what the pipeline would do without calling any LLM agents.

    Returns task names, their current status, and constraint profiles that would apply.
    No API calls, no cost. Use this before crucis_run to verify everything is configured.

    Args:
        objective_path: Path to objective YAML.
        task_names: Optional list of specific task names.
        profiles: Path to constraint profiles YAML.
        workspace: Workspace directory root.
    """
    from crucis.constraints.loader import load_profiles, resolve_constraints
    from crucis.core.planner import load_plan
    from crucis.intake.objective import parse_objective
    from crucis.persistence.checkpoint import load_checkpoint

    try:
        ctx = _ctx(workspace)
        _ensure_settings(ctx.workspace)
        obj_path = safe_resolve_path(objective_path, ctx.objective_path, ctx.workspace)
        prof_path = safe_resolve_path(profiles, ctx.profiles_path, ctx.workspace)
        ckpt_path = ctx.checkpoint_path

        objective = parse_objective(obj_path)
        profiles_data = load_profiles(prof_path)
        state = load_checkpoint(ckpt_path)
        plan = load_plan(ctx.workspace)

        effective_tasks = objective.tasks or [objective]
        if task_names:
            effective_tasks = [t for t in effective_tasks if t.name in task_names]

        previews = []
        for task in effective_tasks:
            constraints = resolve_constraints(
                objective, profiles_data, task.name, scope="tests"
            )
            # Check existing progress
            existing_status = "pending"
            has_suite = False
            if state:
                for p in state.task_progress:
                    if p.name == task.name:
                        existing_status = p.status.value
                        has_suite = bool(p.train_suite_source)
                        break

            previews.append({
                "task_name": task.name,
                "description": task.description[:200] if task.description else "",
                "current_status": existing_status,
                "has_existing_suite": has_suite,
                "constraint_profile": objective.tests_constraint_profile or "default",
                "primary_constraints": {
                    "max_complexity": constraints.primary.max_cyclomatic_complexity,
                    "max_lines_per_function": constraints.primary.max_lines_per_function,
                } if constraints.primary else {},
                "train_eval_count": len(task.train_evals or []),
                "holdout_eval_count": len(task.holdout_evals or []),
            })

        return {
            "dry_run": True,
            "objective_name": objective.name,
            "has_plan": plan is not None,
            "tasks": previews,
            "resolved_paths": {
                "objective": str(obj_path),
                "profiles": str(prof_path),
                "checkpoint": str(ckpt_path),
            },
            "next_steps": [
                "If everything looks correct, run crucis_run or crucis_run_fit",
                "Use crucis_get_prompt to preview the exact prompt for a specific task",
            ],
        }
    except Exception as exc:
        return _error(exc)


@mcp.tool(annotations=_DESTRUCTIVE)
async def crucis_reset(
    task_names: list[str] | None = None,
    checkpoint: str | None = None,
    workspace: str | None = None,
) -> dict:
    """Reset checkpoint state — all tasks or specific named tasks.

    Destructive: deletes progress. If task_names is omitted, deletes the entire
    checkpoint (fresh start). If task_names is provided, resets only those tasks.

    Args:
        task_names: Specific tasks to reset. Omit to reset everything.
        checkpoint: Path to checkpoint JSON.
        workspace: Workspace directory root.
    """
    from crucis.models import TrainingStatus
    from crucis.persistence.checkpoint import load_checkpoint, save_checkpoint

    try:
        ctx = _ctx(workspace)
        ckpt_path = safe_resolve_path(checkpoint, ctx.checkpoint_path, ctx.workspace)

        if task_names is None:
            if ckpt_path.exists():
                ckpt_path.unlink()
            return {
                "reset": "all",
                "checkpoint": str(ckpt_path),
                "next_steps": ["Run crucis_run or crucis_run_fit to start fresh"],
            }

        state = load_checkpoint(ckpt_path)
        if state is None:
            return {"error": f"No checkpoint found at {ckpt_path}."}

        reset_names = []
        for task in state.task_progress:
            if task.name in task_names:
                task.status = TrainingStatus.pending
                task.train_suite_source = None
                task.adversarial_report = None
                reset_names.append(task.name)
        save_checkpoint(state, ckpt_path)
        return {
            "reset": reset_names,
            "checkpoint": str(ckpt_path),
            "next_steps": ["Run crucis_run or crucis_run_fit to regenerate reset tasks"],
        }
    except Exception as exc:
        return _error(exc)


@mcp.tool(annotations=_READ_ONLY)
async def crucis_validate(
    objective_path: str | None = None,
    profiles: str | None = None,
    workspace: str | None = None,
    static: bool = False,
) -> dict:
    """Validate an objective YAML file for structural and schema correctness.

    Fast, read-only check. Parses the objective, checks field shapes, eval syntax,
    and optionally runs LLM semantic review. Use this after editing objective.yaml
    to catch issues before running the pipeline. Set static=true to skip the LLM review.

    Args:
        objective_path: Path to objective YAML.
        profiles: Path to profiles YAML to validate references against.
        workspace: Workspace directory for resolving relative paths.
        static: Run only structural checks, skip LLM semantic review.
    """
    from crucis.config import Config
    from crucis.constraints.loader import load_profiles
    from crucis.intake.objective import parse_objective, review_objective_semantics

    try:
        ctx = _ctx(workspace)
        obj_path = safe_resolve_path(objective_path, ctx.objective_path, ctx.workspace)
        objective = parse_objective(obj_path)

        issues = []
        if not static:
            _ensure_settings(ctx.workspace)
            config = Config()
            try:
                issues = review_objective_semantics(
                    objective,
                    agent=config.critic_agent,
                    model=config.critic_model,
                    budget=config.max_budget_usd,
                )
            except RuntimeError:
                pass  # Semantic review unavailable, structural check still valid

        profiles_valid = None
        if profiles:
            prof_path = safe_resolve_path(profiles, ctx.profiles_path, ctx.workspace)
            try:
                profiles_data = load_profiles(prof_path)
                profile_name = objective.tests_constraint_profile or "default"
                profiles_valid = profile_name in profiles_data
            except ValueError as exc:
                profiles_valid = False

        has_error = any(i.get("severity") == "error" for i in issues)
        valid = not has_error
        result = {
            "valid": valid,
            "name": objective.name,
            "tasks": [t.name for t in objective.tasks],
            "task_count": len(objective.tasks),
            "issues": issues,
            "profiles_valid": profiles_valid,
        }
        if valid:
            result["next_steps"] = [
                "Run crucis_doctor to check environment prerequisites",
                "Run crucis_dry_run to preview the pipeline configuration",
                "Run crucis_run to execute the full pipeline",
            ]
        else:
            result["next_steps"] = [
                "Fix the issues listed above in objective.yaml, then re-validate",
            ]
        return result
    except (ValueError, FileNotFoundError, WorkspaceNotAuthorizedError) as exc:
        return {"valid": False, "error": str(exc),
                "hint": "Check that the file exists and is valid YAML."}


@mcp.tool(annotations=_READ_ONLY)
async def crucis_summary(
    task_name: str | None = None,
    checkpoint: str | None = None,
    workspace: str | None = None,
) -> dict:
    """Get current pipeline status from the checkpoint.

    Read-only status check. Without task_name: returns overview of all tasks with
    status and optimizer info. With task_name: returns detailed view including test
    suite source code and adversarial report.

    Args:
        task_name: Optional task name for detailed single-task view.
        checkpoint: Path to checkpoint JSON.
        workspace: Workspace directory root.
    """
    from crucis.persistence.checkpoint import load_checkpoint
    from crucis.persistence.policy import load_optimizer_status

    try:
        ctx = _ctx(workspace)
        ckpt_path = safe_resolve_path(checkpoint, ctx.checkpoint_path, ctx.workspace)
        state = load_checkpoint(ckpt_path)
        if state is None:
            return {"found": False, "error": f"No checkpoint at {ckpt_path}."}

        if task_name:
            for p in state.task_progress:
                if p.name == task_name:
                    detail = {
                        "found": True,
                        "name": p.name,
                        "status": p.status.value,
                        "train_suite_source": p.train_suite_source,
                        "adversarial_report": (
                            p.adversarial_report.model_dump(mode="json")
                            if p.adversarial_report is not None else None
                        ),
                    }
                    # Contextual next steps based on task status
                    status = p.status.value
                    if status == "pending":
                        detail["next_steps"] = ["Run crucis_run_fit to generate tests"]
                    elif status in ("train_suite_generated", "train_suite_approved"):
                        detail["next_steps"] = ["Run crucis_run_fit to continue adversarial review"]
                    elif status == "adversarially_reviewed":
                        detail["next_steps"] = ["Run crucis_run_evaluate to implement and verify"]
                    elif status == "complete":
                        detail["next_steps"] = ["Task is complete."]
                    return detail
            available = [p.name for p in state.task_progress]
            return {
                "found": False,
                "error": f"Task '{task_name}' not found in checkpoint.",
                "available_tasks": available,
            }

        opt_status = load_optimizer_status(ctx.workspace)
        payload = {"found": True, **_checkpoint_payload(state, ckpt_path, opt_status)}
        # Add contextual next steps
        ready = payload["summary"]["ready_for_evaluation"]
        passed = payload["summary"]["evaluation_passed"]
        if passed:
            payload["next_steps"] = ["Pipeline complete. All tasks passed."]
        elif ready:
            payload["next_steps"] = ["All tasks ready. Run crucis_run_evaluate to implement."]
        else:
            pending = [t["name"] for t in payload["tasks"] if t["status"] == "pending"]
            if pending:
                payload["next_steps"] = [
                    f"Run crucis_run_fit to process remaining tasks: {pending}",
                ]
            else:
                payload["next_steps"] = [
                    "Use crucis_summary with task_name to inspect individual tasks",
                ]
        return payload
    except Exception as exc:
        return _error(exc)


@mcp.tool(annotations=_READ_ONLY)
async def crucis_doctor(
    workspace: str | None = None,
    objective_path: str | None = None,
    profiles: str | None = None,
    checkpoint: str | None = None,
    require_docker: bool = False,
) -> dict:
    """Run environment and workspace diagnostics.

    Read-only health check. Verifies Python version, agent binaries, API keys,
    Docker availability, and workspace config files. Run this before crucis_run
    to catch missing prerequisites early.

    Args:
        workspace: Workspace directory to check.
        objective_path: Optional objective file to validate.
        profiles: Optional profiles file to validate.
        checkpoint: Optional checkpoint file to validate.
        require_docker: Fail when Docker is unavailable.
    """
    from crucis.config import Config
    from crucis.diagnostics import doctor_report_payload, run_doctor
    from crucis.persistence.settings import apply_agent_settings_to_env, try_load_runtime_settings

    try:
        ws = resolve_workspace(workspace)
        check_workspace_authorized(ws)
        settings = try_load_runtime_settings(ws)
        if settings is not None:
            apply_agent_settings_to_env(settings)

        report = run_doctor(
            workspace=ws,
            objective_path=Path(objective_path) if objective_path else None,
            profiles_path=Path(profiles) if profiles else None,
            checkpoint_path=Path(checkpoint) if checkpoint else None,
            require_docker=require_docker,
            config=Config(),
        )
        payload = doctor_report_payload(report)
        failed = [c for c in payload.get("checks", []) if c.get("status") == "fail"]
        if failed:
            payload["next_steps"] = [
                f"Fix: {c['message']}" + (f" — {c['hint']}" if c.get("hint") else "")
                for c in failed
            ]
        else:
            payload["next_steps"] = ["Environment is ready. Run crucis_run to start."]
        return payload
    except Exception as exc:
        return _error(exc)


@mcp.tool(annotations=_MUTATING)
async def crucis_promote(
    run_id: str,
    force: bool = False,
    workspace: str | None = None,
) -> dict:
    """Promote an optimizer candidate policy to active.

    Replaces the active optimizer policy with the winning candidate from
    a completed optimization run.

    Args:
        run_id: Run ID of the candidate to promote.
        force: Promote even when candidate-ready metadata is missing.
        workspace: Workspace directory root.
    """
    from crucis.persistence.policy import (
        OptimizerState,
        OptimizerStatus,
        load_candidate_policy,
        load_optimizer_status,
        save_active_policy,
        save_optimizer_status,
    )

    try:
        ws = resolve_workspace(workspace)
        check_workspace_authorized(ws)
        status = load_optimizer_status(ws)

        if not force:
            if status is None:
                return _error(
                    ValueError("No optimizer status found."),
                    hint="Use force=true to override, or run the optimizer first.",
                )
            if not status.candidate_ready or status.candidate_run_id != run_id:
                return _error(
                    ValueError(f"Run '{run_id}' is not candidate-ready."),
                    hint="Use force=true to override.",
                )

        candidate = load_candidate_policy(ws, run_id)
        save_active_policy(candidate, ws)

        next_status = status or OptimizerStatus()
        next_status.state = OptimizerState.completed
        next_status.last_run_id = run_id
        next_status.promoted = True
        next_status.active_policy_version = run_id
        next_status.candidate_ready = False
        next_status.candidate_run_id = None
        next_status.message = f"promoted candidate from run {run_id}"
        next_status.updated_at = datetime.now(UTC).isoformat()
        save_optimizer_status(ws, next_status)

        return {
            "run_id": run_id,
            "promoted": True,
            "optimizer_state": next_status.model_dump(mode="json"),
        }
    except Exception as exc:
        return _error(exc)


@mcp.tool(annotations=_LLM_CALL)
async def crucis_optimizer_worker(
    loop: bool = False,
    workspace: str | None = None,
) -> dict:
    """Run the background optimizer worker to process queued jobs.

    Drains optimization jobs and evaluates candidate policies. Can run
    once (default) or in continuous loop mode.

    Args:
        loop: Run continuously instead of one-shot.
        workspace: Workspace directory root.
    """
    from crucis.execution.optimizer import run_optimizer_worker

    try:
        ws = resolve_workspace(workspace)
        check_workspace_authorized(ws)
        ev_loop = asyncio.get_event_loop()
        exit_code = await ev_loop.run_in_executor(
            None, lambda: run_optimizer_worker(ws, once=not loop)
        )
        return {
            "workspace": str(ws),
            "mode": "loop" if loop else "once",
            "exit_code": exit_code,
            "next_steps": (
                ["Use crucis_promote to promote the winning candidate"]
                if exit_code == 0 else
                ["Check optimizer logs for errors"]
            ),
        }
    except Exception as exc:
        return _error(exc)


@mcp.tool(annotations=_READ_ONLY)
async def crucis_check_constraints(
    source_code: str,
    task_name: str | None = None,
    scope: str = "tests",
    objective_path: str | None = None,
    profiles: str | None = None,
) -> dict:
    """Check Python source code against Crucis constraint profiles.

    Read-only static analysis. Reports cyclomatic complexity, line counts, and AST
    checks against primary (blocking) and secondary (advisory) gates. Use this to
    validate test suites or implementation code before submitting.

    Args:
        source_code: Python source code to check (max 1 MB).
        task_name: Task name for task-specific constraint overrides.
        scope: "tests" or "implementation" constraint scope.
        objective_path: Path to objective YAML for profile resolution.
        profiles: Path to profiles YAML.
    """
    from crucis.constraints.checker import check_constraints
    from crucis.constraints.loader import load_profiles, resolve_constraints
    from crucis.intake.objective import parse_objective

    try:
        validate_source_input(source_code)
        ctx = _ctx()
        obj_path = safe_resolve_path(objective_path, ctx.objective_path, ctx.workspace)
        prof_path = safe_resolve_path(profiles, ctx.profiles_path, ctx.workspace)

        objective = parse_objective(obj_path)
        profiles_data = load_profiles(prof_path)
        constraints = resolve_constraints(objective, profiles_data, task_name, scope=scope)

        primary_result, secondary_result = check_constraints(source_code, constraints)

        result = {
            "primary": {
                "passed": primary_result.passed,
                "violations": primary_result.violations,
                "metrics": primary_result.metrics,
            },
            "secondary": {
                "passed": secondary_result.passed,
                "violations": secondary_result.violations,
                "metrics": secondary_result.metrics,
            },
        }
        if not primary_result.passed:
            result["next_steps"] = [
                "Fix primary constraint violations (these are blocking), then re-check",
            ]
        elif not secondary_result.passed:
            result["next_steps"] = [
                "Primary constraints pass. Secondary violations are advisory — fix if possible",
            ]
        else:
            result["next_steps"] = ["All constraints pass."]
        return result
    except (InputTooLargeError, PathTraversalError, WorkspaceNotAuthorizedError) as exc:
        return _error(exc)
    except Exception as exc:
        return _error(exc)


# ===================================================================
# PART B: Step-by-Step Tools (6) — Agent-as-Implementer Mode
# ===================================================================


@mcp.tool(annotations=_READ_ONLY)
async def crucis_get_prompt(
    step: str,
    task_name: str | None = None,
    objective_path: str | None = None,
    profiles: str | None = None,
    checkpoint: str | None = None,
    workspace: str | None = None,
    constraint_feedback: str = "",
    adversary_feedback: str = "",
    error_feedback: str = "",
) -> dict:
    """Get the system prompt Crucis would send to a subprocess agent.

    Read-only. Returns the exact prompt for generation, adversary, or evaluation
    so you can do the work yourself (step-by-step mode). step must be one of:
    "generation", "adversary", "evaluation". task_name is required for generation
    and adversary steps.

    Args:
        step: Pipeline step — "generation", "adversary", or "evaluation".
        task_name: Task name (required for generation and adversary steps).
        objective_path: Path to objective YAML.
        profiles: Path to constraint profiles YAML.
        checkpoint: Path to checkpoint JSON.
        workspace: Workspace directory root.
        constraint_feedback: Constraint violation feedback for generation retry.
        adversary_feedback: Adversarial feedback for generation retry.
        error_feedback: Error feedback for evaluation retry.
    """
    from crucis.constraints.loader import load_profiles, resolve_constraints
    from crucis.core.planner import load_plan
    from crucis.core.prompts import (
        build_adversary_prompt,
        build_evaluation_prompt,
        build_generation_prompt,
    )
    from crucis.intake.objective import parse_objective
    from crucis.persistence.checkpoint import load_checkpoint

    try:
        ctx = _ctx(workspace)
        _ensure_settings(ctx.workspace)
        obj_path = safe_resolve_path(objective_path, ctx.objective_path, ctx.workspace)
        objective = parse_objective(obj_path)

        if step == "generation":
            prof_path = safe_resolve_path(profiles, ctx.profiles_path, ctx.workspace)
            profiles_data = load_profiles(prof_path)
            constraints = resolve_constraints(objective, profiles_data, task_name, scope="tests")
            task_obj = _build_task_objective(task_name, objective)

            plan_content = load_plan(ctx.workspace) or ""
            prompt = build_generation_prompt(
                task_obj, constraints,
                constraint_feedback=constraint_feedback,
                adversarial_feedback=adversary_feedback,
                plan_content=plan_content,
            )
            return {
                "step": "generation",
                "task_name": task_name,
                "prompt": prompt,
                "next_steps": [
                    "Write a complete pytest test suite based on this prompt",
                    "Use crucis_submit_test_suite to validate and save it",
                ],
            }

        elif step == "adversary":
            ckpt_path = safe_resolve_path(checkpoint, ctx.checkpoint_path, ctx.workspace)
            state = load_checkpoint(ckpt_path)
            if state is None:
                return {"error": "No checkpoint found. Generate tests first."}

            train_source = None
            for p in state.task_progress:
                if p.name == task_name:
                    train_source = p.train_suite_source
                    break
            if not train_source:
                return {"error": f"No test suite found for task '{task_name}'."}

            prof_path = safe_resolve_path(profiles, ctx.profiles_path, ctx.workspace)
            profiles_data = load_profiles(prof_path)
            constraints = resolve_constraints(objective, profiles_data, task_name, scope="tests")
            task_obj = _build_task_objective(task_name, objective)

            prompt = build_adversary_prompt(train_source, task_obj, constraints)
            return {
                "step": "adversary",
                "task_name": task_name,
                "prompt": prompt,
                "next_steps": [
                    "Review the test suite for weaknesses based on this prompt",
                    "Use crucis_submit_adversarial_report to save your findings",
                    "Use crucis_run_probe to verify test robustness with a cheating probe",
                ],
            }

        elif step == "evaluation":
            ckpt_path = safe_resolve_path(checkpoint, ctx.checkpoint_path, ctx.workspace)
            state = load_checkpoint(ckpt_path)
            if state is None:
                return {"error": "No checkpoint found. Run fit phase first."}

            # Write test files and build curriculum path
            from crucis.core.loop import _write_generated_tests

            test_dir = ctx.workspace / "tests"
            test_dir.mkdir(parents=True, exist_ok=True)
            test_paths = _write_generated_tests(state, test_dir)

            curriculum_path = ctx.workspace / "brief.md"
            prompt = build_evaluation_prompt(
                test_paths,
                curriculum_path=curriculum_path if curriculum_path.exists() else None,
                error_feedback=error_feedback,
            )
            return {
                "step": "evaluation",
                "prompt": prompt,
                "test_paths": [str(p) for p in test_paths],
                "next_steps": [
                    "Implement code that passes all the test files listed above",
                    "Use crucis_verify_implementation to verify your code",
                ],
            }

        else:
            return _error(
                ValueError(f"Unknown step '{step}'."),
                hint="step must be 'generation', 'adversary', or 'evaluation'.",
            )

    except Exception as exc:
        return _error(exc)


@mcp.tool(annotations=_MUTATING)
async def crucis_submit_test_suite(
    task_name: str,
    test_source: str,
    objective_path: str | None = None,
    profiles: str | None = None,
    checkpoint: str | None = None,
    workspace: str | None = None,
) -> dict:
    """Save an agent-generated test suite, validate it, and update the checkpoint.

    Validates syntax (AST parse) and constraints (primary + secondary gates),
    then saves to checkpoint. Use after writing tests based on crucis_get_prompt
    output. If constraints fail, fix violations and resubmit.

    Args:
        task_name: Name of the task this test suite belongs to.
        test_source: Complete pytest test suite source code (max 1 MB).
        objective_path: Path to objective YAML.
        profiles: Path to constraint profiles YAML.
        checkpoint: Path to checkpoint JSON.
        workspace: Workspace directory root.
    """
    from crucis.constraints.loader import load_profiles, resolve_constraints
    from crucis.core.loop import validate_train_suite_constraints, validate_train_suite_syntax
    from crucis.intake.objective import parse_objective
    from crucis.models import CheckpointState, TaskProgress, TrainingStatus
    from crucis.persistence.checkpoint import load_checkpoint, save_checkpoint

    try:
        validate_source_input(test_source)
        ctx = _ctx(workspace)
        obj_path = safe_resolve_path(objective_path, ctx.objective_path, ctx.workspace)
        prof_path = safe_resolve_path(profiles, ctx.profiles_path, ctx.workspace)
        ckpt_path = safe_resolve_path(checkpoint, ctx.checkpoint_path, ctx.workspace)

        # Validate syntax
        syntax_ok, syntax_msg = validate_train_suite_syntax(test_source)
        if not syntax_ok:
            return {"accepted": False, "syntax_valid": False, "error": syntax_msg}

        # Validate constraints
        objective = parse_objective(obj_path)
        profiles_data = load_profiles(prof_path)
        constraints = resolve_constraints(objective, profiles_data, task_name, scope="tests")
        constraints_ok, constraints_msg = validate_train_suite_constraints(test_source, constraints)

        # Load or create checkpoint
        state = load_checkpoint(ckpt_path)
        if state is None:
            effective_tasks = objective.tasks or [objective]
            state = CheckpointState(
                task_progress=[TaskProgress(name=t.name) for t in effective_tasks]
            )

        # Update task progress
        found = False
        for p in state.task_progress:
            if p.name == task_name:
                p.train_suite_source = test_source
                p.status = TrainingStatus.train_suite_approved
                found = True
                break

        if not found:
            state.task_progress.append(TaskProgress(
                name=task_name,
                status=TrainingStatus.train_suite_approved,
                train_suite_source=test_source,
            ))

        save_checkpoint(state, ckpt_path)

        from crucis.constraints.checker import check_constraints
        primary_result, secondary_result = check_constraints(test_source, constraints)

        result = {
            "accepted": True,
            "syntax_valid": True,
            "constraints_passed": constraints_ok,
            "constraints_message": constraints_msg if not constraints_ok else "",
            "primary": {
                "passed": primary_result.passed,
                "violations": primary_result.violations,
                "metrics": primary_result.metrics,
            },
            "secondary": {
                "passed": secondary_result.passed,
                "violations": secondary_result.violations,
                "metrics": secondary_result.metrics,
            },
            "task_status": "train_suite_approved",
        }
        if not constraints_ok:
            result["next_steps"] = [
                "Fix constraint violations in your test suite and resubmit",
            ]
        else:
            result["next_steps"] = [
                "Use crucis_get_prompt(step='adversary') to review your tests",
                "Or use crucis_run_probe to check test robustness directly",
            ]
        return result
    except Exception as exc:
        return _error(exc)


@mcp.tool(annotations=_MUTATING)
async def crucis_submit_adversarial_report(
    task_name: str,
    attack_vectors: list[str],
    generalization_gaps: list[str],
    suggested_probe_tests: list[str],
    correctness_issues: list[str] | None = None,
    checkpoint: str | None = None,
    workspace: str | None = None,
) -> dict:
    """Save adversarial review findings and update the checkpoint.

    Records attack vectors, generalization gaps, and probe suggestions. Use after
    reviewing tests with crucis_get_prompt(step='adversary'). Follow up with
    crucis_run_probe to verify test robustness.

    Args:
        task_name: Name of the task this report belongs to.
        attack_vectors: Ways a cheating implementation could pass the tests.
        generalization_gaps: Missing edge cases or input categories.
        suggested_probe_tests: Specific test cases to probe weaknesses.
        correctness_issues: Issues with test correctness itself.
        checkpoint: Path to checkpoint JSON.
        workspace: Workspace directory root.
    """
    from crucis.models import AdversarialReport, TrainingStatus
    from crucis.persistence.checkpoint import load_checkpoint, save_checkpoint

    try:
        ctx = _ctx(workspace)
        ckpt_path = safe_resolve_path(checkpoint, ctx.checkpoint_path, ctx.workspace)
        state = load_checkpoint(ckpt_path)
        if state is None:
            return {"error": "No checkpoint found. Submit test suite first."}

        report = AdversarialReport(
            attack_vectors=attack_vectors,
            generalization_gaps=generalization_gaps,
            suggested_probe_tests=suggested_probe_tests,
            correctness_issues=correctness_issues or [],
        )

        found = False
        for p in state.task_progress:
            if p.name == task_name:
                p.adversarial_report = report
                p.status = TrainingStatus.adversarially_reviewed
                found = True
                break

        if not found:
            return {"error": f"Task '{task_name}' not found in checkpoint."}

        save_checkpoint(state, ckpt_path)
        return {
            "accepted": True,
            "task_status": "adversarially_reviewed",
            "findings_count": {
                "attack_vectors": len(attack_vectors),
                "generalization_gaps": len(generalization_gaps),
                "suggested_probe_tests": len(suggested_probe_tests),
                "correctness_issues": len(correctness_issues or []),
            },
            "next_steps": [
                "Use crucis_run_probe to run a cheating probe against the tests",
                "If probe passes (tests are weak), regenerate tests with feedback",
            ],
        }
    except Exception as exc:
        return _error(exc)


@mcp.tool(annotations=_LLM_CALL)
async def crucis_run_probe(
    task_name: str,
    objective_path: str | None = None,
    checkpoint: str | None = None,
    workspace: str | None = None,
) -> dict:
    """Run a cheating probe against a task's test suite.

    Generates a deliberately cheating implementation and runs it against the tests.
    If probe_passed=true → tests are WEAK (a cheat passes them — regenerate tests).
    If probe_passed=false → tests are ROBUST (cheat fails — proceed to implement).

    Args:
        task_name: Task whose test suite to probe.
        objective_path: Path to objective YAML.
        checkpoint: Path to checkpoint JSON.
        workspace: Workspace directory root.
    """
    from crucis.config import Config
    from crucis.core.adversary import run_adversarial_probe
    from crucis.intake.objective import parse_objective
    from crucis.persistence.checkpoint import load_checkpoint

    try:
        ctx = _ctx(workspace)
        _ensure_settings(ctx.workspace)
        obj_path = safe_resolve_path(objective_path, ctx.objective_path, ctx.workspace)
        ckpt_path = safe_resolve_path(checkpoint, ctx.checkpoint_path, ctx.workspace)

        state = load_checkpoint(ckpt_path)
        if state is None:
            return {"error": "No checkpoint found."}

        train_source = None
        for p in state.task_progress:
            if p.name == task_name:
                train_source = p.train_suite_source
                break
        if not train_source:
            return {"error": f"No test suite for task '{task_name}'."}

        objective = parse_objective(obj_path)
        task_obj = _build_task_objective(task_name, objective)

        config = Config()
        loop = asyncio.get_event_loop()
        probe_passed, probe_code = await loop.run_in_executor(
            None, lambda: run_adversarial_probe(train_source, task_obj, config)
        )

        result = {
            "probe_passed": probe_passed,
            "probe_code": probe_code,
            "tests_are_weak": probe_passed,
        }
        if probe_passed:
            result["next_steps"] = [
                "Tests are WEAK — a cheating implementation passed them",
                "Regenerate tests: crucis_get_prompt(step='generation') with adversary_feedback",
            ]
        else:
            result["next_steps"] = [
                "Tests are robust. Use crucis_write_tests to materialize them to disk",
                "Then implement code and use crucis_verify_implementation",
            ]
        return result
    except Exception as exc:
        return _error(exc)


@mcp.tool(annotations=_MUTATING)
async def crucis_write_tests(
    checkpoint: str | None = None,
    test_dir: str = "tests",
    workspace: str | None = None,
) -> dict:
    """Write test suites from checkpoint to disk as pytest files.

    Materializes tests/test_<task>.py for all tasks with test suites. Required
    before crucis_verify_implementation — tests must exist on disk for pytest.

    Args:
        checkpoint: Path to checkpoint JSON.
        test_dir: Directory for test files (default: "tests").
        workspace: Workspace directory root.
    """
    from crucis.core.loop import _write_generated_tests
    from crucis.persistence.checkpoint import load_checkpoint

    try:
        ctx = _ctx(workspace)
        ckpt_path = safe_resolve_path(checkpoint, ctx.checkpoint_path, ctx.workspace)
        state = load_checkpoint(ckpt_path)
        if state is None:
            return {"error": "No checkpoint found."}

        target_dir = ctx.workspace / test_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        written = _write_generated_tests(state, target_dir)
        return {
            "written": [str(p) for p in written],
            "test_count": len(written),
            "next_steps": [
                "Implement code that passes these tests",
                "Use crucis_verify_implementation to verify your implementation",
            ],
        }
    except Exception as exc:
        return _error(exc)


@mcp.tool(annotations=_READ_ONLY)
async def crucis_verify_implementation(
    task_name: str | None = None,
    objective_path: str | None = None,
    no_sandbox: bool = True,
    checkpoint: str | None = None,
    test_dir: str = "tests",
    workspace: str | None = None,
) -> dict:
    """Run tests + holdout evals to verify implementation correctness.

    Runs pytest on generated test files and checks holdout evaluations separately.
    Use crucis_write_tests first to materialize tests to disk. The test_output
    field contains the last 4000 chars of pytest output (where failures appear).

    Args:
        task_name: Optional task to verify. Omit to verify all tasks.
        objective_path: Path to objective YAML.
        no_sandbox: Skip Docker sandbox (default: true).
        checkpoint: Path to checkpoint JSON.
        test_dir: Directory containing test files.
        workspace: Workspace directory root.
    """
    from crucis.core.loop import (
        _collect_holdout_eval_specs,
        _run_holdout_eval_checks,
        _run_pytest_targets,
        _validated_unit_name,
    )
    from crucis.intake.objective import parse_objective
    from crucis.persistence.checkpoint import load_checkpoint

    try:
        ctx = _ctx(workspace)
        obj_path = safe_resolve_path(objective_path, ctx.objective_path, ctx.workspace)
        ckpt_path = safe_resolve_path(checkpoint, ctx.checkpoint_path, ctx.workspace)

        state = load_checkpoint(ckpt_path)
        if state is None:
            return {"error": "No checkpoint found."}

        objective = parse_objective(obj_path)
        target_dir = ctx.workspace / test_dir
        use_sandbox = not no_sandbox

        # Collect test file paths
        test_paths = []
        for p in state.task_progress:
            if task_name and p.name != task_name:
                continue
            if not p.train_suite_source:
                continue
            safe_name = _validated_unit_name(p.name, "VERIFY")
            path = target_dir / f"test_{safe_name}.py"
            if path.exists():
                test_paths.append(path)

        if not test_paths:
            return {"error": "No test files found.", "hint": "Run crucis_write_tests first to materialize tests to disk."}

        loop = asyncio.get_event_loop()

        # Run tests
        tests_passed, test_output = await loop.run_in_executor(
            None, lambda: _run_pytest_targets(ctx.workspace, test_paths, use_sandbox)
        )

        # Run holdout evals
        holdout_specs = _collect_holdout_eval_specs(state, objective)
        if task_name:
            holdout_specs = {k: v for k, v in holdout_specs.items() if k == task_name}

        holdout_passed = True
        holdout_output = ""
        holdout_total = sum(len(v.holdout_evals) for v in holdout_specs.values())

        if holdout_specs:
            holdout_passed, holdout_output = await loop.run_in_executor(
                None, lambda: _run_holdout_eval_checks(target_dir, use_sandbox, holdout_specs)
            )

        overall = tests_passed and holdout_passed
        # Keep the tail of test output — that's where failures and the summary appear
        trimmed_output = test_output[-4000:] if test_output and len(test_output) > 4000 else (test_output or "")
        if test_output and len(test_output) > 4000:
            trimmed_output = f"[...truncated {len(test_output) - 4000} chars...]\n" + trimmed_output
        result = {
            "tests_passed": tests_passed,
            "holdout_passed": holdout_passed,
            "overall": overall,
            "test_output": trimmed_output,
            "holdout_total": holdout_total,
        }
        if overall:
            result["next_steps"] = ["All tests and holdout evals pass. Implementation is verified."]
        else:
            steps = []
            if not tests_passed:
                steps.append("Fix failing tests — see test_output for pytest failures")
            if not holdout_passed:
                steps.append("Fix holdout eval failures — hidden evals are not passing")
            steps.append("Re-run crucis_verify_implementation after fixing")
            result["next_steps"] = steps
        return result
    except Exception as exc:
        return _error(exc, hint="Ensure crucis_write_tests was called first.")


# ===================================================================
# RESOURCES (7)
# ===================================================================


@mcp.resource("crucis://objective")
async def get_objective() -> str:
    """The current Crucis objective definition parsed from objective.yaml."""
    from crucis.intake.objective import parse_objective

    try:
        ctx = _ctx()
        objective = parse_objective(ctx.objective_path)
        return objective.model_dump_json(indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.resource("crucis://checkpoint")
async def get_checkpoint() -> str:
    """Current pipeline checkpoint state showing per-task progress."""
    from crucis.persistence.checkpoint import load_checkpoint

    try:
        ctx = _ctx()
        state = load_checkpoint(ctx.checkpoint_path)
        if state is None:
            return json.dumps({"error": "No checkpoint found."})
        return state.model_dump_json(indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.resource("crucis://task/{task_name}/test-suite")
async def get_task_test_suite(task_name: str) -> str:
    """Generated pytest test suite source for a specific task."""
    from crucis.persistence.checkpoint import load_checkpoint

    try:
        ctx = _ctx()
        state = load_checkpoint(ctx.checkpoint_path)
        if state is None:
            return "No checkpoint found."
        for p in state.task_progress:
            if p.name == task_name:
                return p.train_suite_source or "No test suite generated yet."
        return f"Task '{task_name}' not found in checkpoint."
    except Exception as exc:
        return f"Error: {exc}"


@mcp.resource("crucis://task/{task_name}/adversarial-report")
async def get_task_adversarial_report(task_name: str) -> str:
    """Adversarial review report for a specific task's test suite."""
    from crucis.persistence.checkpoint import load_checkpoint

    try:
        ctx = _ctx()
        state = load_checkpoint(ctx.checkpoint_path)
        if state is None:
            return json.dumps({"error": "No checkpoint found."})
        for p in state.task_progress:
            if p.name == task_name:
                if p.adversarial_report is None:
                    return json.dumps({"error": "No adversarial report yet."})
                return p.adversarial_report.model_dump_json(indent=2)
        return json.dumps({"error": f"Task '{task_name}' not found."})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.resource("crucis://constraints/{profile_name}")
async def get_constraint_profile(profile_name: str) -> str:
    """Constraint profile definition showing primary and secondary gates."""
    from crucis.constraints.loader import load_profiles

    try:
        ctx = _ctx()
        profiles = load_profiles(ctx.profiles_path)
        if profile_name not in profiles:
            available = [k for k in profiles if k != "tasks"]
            return json.dumps({
                "error": f"Profile '{profile_name}' not found. Available: {available}"
            })
        return json.dumps(profiles[profile_name], indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.resource("crucis://plan")
async def get_plan() -> str:
    """Generated plan.md content for test-suite generation strategy."""
    from crucis.core.planner import load_plan

    try:
        ctx = _ctx()
        content = load_plan(ctx.workspace)
        return content or "No plan.md found. Use crucis_run_plan to generate one."
    except Exception as exc:
        return f"Error: {exc}"


@mcp.resource("crucis://curriculum")
async def get_curriculum() -> str:
    """Generated curriculum/brief markdown for the implementation agent."""
    try:
        ctx = _ctx()
        brief_path = ctx.workspace / "brief.md"
        if not brief_path.exists():
            return "No brief.md found. Brief is generated during the evaluation phase."
        return brief_path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"Error: {exc}"


# ===================================================================
# PROMPTS (5)
# ===================================================================


@mcp.prompt()
async def setup_crucis(
    function_name: str,
    function_description: str,
) -> str:
    """Set up a Crucis verification pipeline for a new function.

    Args:
        function_name: Name of the function to verify.
        function_description: What the function should do.
    """
    return (
        f"Set up a Crucis verification pipeline for `{function_name}`: "
        f"{function_description}\n\n"
        "Steps:\n"
        "1. Use crucis_init to scaffold the workspace if no objective.yaml exists\n"
        "2. Edit objective.yaml:\n"
        f"   - Set name to '{function_name}'\n"
        f"   - Set description to explain the behavior\n"
        f"   - Set signature to the function signature\n"
        "   - Add train evals (visible input/output pairs for test generation)\n"
        "   - Add holdout evals (hidden pairs for final verification — "
        "prevents overfitting)\n"
        "   - Set target_files to where the implementation should go\n"
        "3. Use crucis_validate to check the objective is valid\n"
        "4. Use crucis_doctor to verify the environment is ready\n"
        "5. Choose a mode:\n"
        "   a. Pipeline mode: crucis_run to auto-generate+harden+implement\n"
        "   b. Step-by-step: crucis_get_prompt → write tests → "
        "crucis_submit_test_suite → review → crucis_run_probe → "
        "crucis_write_tests → implement → crucis_verify_implementation\n"
        "6. Use crucis_summary to check results"
    )


@mcp.prompt()
async def tdd_workflow(
    objective_path: str = "objective.yaml",
) -> str:
    """Run the complete Crucis TDD workflow using subprocess agents.

    Args:
        objective_path: Path to the objective YAML file.
    """
    return (
        f"Execute the full Crucis TDD pipeline using `{objective_path}`:\n\n"
        "1. crucis_validate — ensure the objective is well-formed\n"
        "2. crucis_doctor — verify environment prerequisites\n"
        "3. crucis_summary — check if there's existing progress to resume\n"
        "4. crucis_run — run the full pipeline (fit+evaluate) with subprocess agents\n"
        "5. crucis_summary — confirm all tasks passed and evaluation succeeded\n\n"
        "If the pipeline fails, use crucis_summary with task_name to inspect "
        "the test suite and adversarial report, then decide whether to "
        "crucis_reset and re-run or fix the objective."
    )


@mcp.prompt()
async def verify_code_quality(
    source_file: str,
    constraint_profile: str = "recommended",
) -> str:
    """Check source code against Crucis constraint profiles.

    Args:
        source_file: Path to the Python file to check.
        constraint_profile: Constraint profile name to use.
    """
    return (
        f"Read `{source_file}` and use crucis_check_constraints to verify it "
        f"against the '{constraint_profile}' constraint profile.\n\n"
        "Report:\n"
        "- Whether primary constraints pass (blocking issues)\n"
        "- Whether secondary constraints pass (quality suggestions)\n"
        "- Specific violations and how to fix them\n"
        "- Key metrics (complexity, line counts, etc.)"
    )


@mcp.prompt()
async def harden_tests(
    objective_path: str = "objective.yaml",
    task_name: str | None = None,
) -> str:
    """Generate and adversarially harden test suites without implementation.

    Args:
        objective_path: Path to the objective YAML file.
        task_name: Optional specific task to harden.
    """
    task_filter = f" for task '{task_name}'" if task_name else ""
    task_arg = f' with task_names=["{task_name}"]' if task_name else ""
    return (
        f"Run the Crucis FIT phase{task_filter} using `{objective_path}`:\n\n"
        "1. crucis_validate — check objective validity\n"
        f"2. crucis_run_fit{task_arg} — generate and harden tests\n"
        "3. crucis_summary — review task status and adversarial reports\n\n"
        "After fit completes, inspect the adversarial report to understand "
        "identified weaknesses and how they were addressed."
    )


@mcp.prompt()
async def agent_tdd_workflow(
    objective_path: str = "objective.yaml",
) -> str:
    """Step-by-step TDD where YOU act as generator, critic, and implementer.

    Args:
        objective_path: Path to the objective YAML file.
    """
    return (
        f"Run Crucis TDD in step-by-step mode using `{objective_path}`.\n"
        "You will act as the test generator, adversarial critic, and implementer.\n\n"
        "For each task in the objective:\n\n"
        "**Phase 1: Generate Tests**\n"
        "1. crucis_get_prompt(step='generation', task_name=...) — get the generation prompt\n"
        "2. Read the prompt and write a complete pytest test suite\n"
        "3. crucis_submit_test_suite(task_name=..., test_source=...) — validate and save\n"
        "   - If constraints fail, fix violations and resubmit\n\n"
        "**Phase 2: Adversarial Review**\n"
        "4. crucis_get_prompt(step='adversary', task_name=...) — get the adversary prompt\n"
        "5. Review the tests: identify attack vectors, generalization gaps\n"
        "6. crucis_submit_adversarial_report(task_name=..., ...) — save findings\n"
        "7. crucis_run_probe(task_name=...) — run cheating probe\n"
        "   - If probe passes: tests are weak. Regenerate from step 1 with feedback\n"
        "   - If probe fails: tests are robust. Continue.\n\n"
        "**Phase 3: Implement**\n"
        "8. crucis_write_tests() — materialize test files to disk\n"
        "9. crucis_get_prompt(step='evaluation') — get the curriculum\n"
        "10. Write implementation code to pass the tests\n"
        "11. crucis_verify_implementation() — run tests + holdout evals\n"
        "    - If failed: fix implementation, re-verify\n"
        "    - If passed: done!"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Run the Crucis MCP server on STDIO transport."""
    from crucis.display import configure_console

    # Redirect Rich output to stderr to prevent STDIO corruption
    configure_console(no_color=True)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
