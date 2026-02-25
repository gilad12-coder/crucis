"""CLI entry point for Crucis."""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from crucis.config import Config
from crucis.constraints.loader import load_profiles, resolve_constraints
from crucis.core.loop import run_evaluation, run_fit
from crucis.core.planner import build_generation_plan, write_plan_to_workspace
from crucis.defaults import DEFAULT_CHECKPOINT_PATH, DEFAULT_PROFILES_PATH
from crucis.diagnostics import collect_preflight_checks, doctor_report_payload, run_doctor
from crucis.display import (
    configure_console,
    display_adversarial_report,
    display_agent_boundary,
    display_checkpoint_table,
    display_doctor_report,
    display_error,
    display_fit_complete,
    display_hardening_cycle,
    display_info,
    display_sandbox_status,
    display_success,
    display_task_header,
    display_test_suite_source,
    display_validation_report,
    display_warning,
    display_workspace,
    prompt_input,
)
from crucis.models import AdversarialReport, TrainingStatus
from crucis.execution.optimizer import run_optimizer_worker
from crucis.execution.sandbox import check_docker_available
from crucis.intake.objective import parse_objective, review_objective_semantics
from crucis.intake.scaffold import detect_existing_codebase, scaffold_workspace
from crucis.persistence.checkpoint import load_checkpoint, save_checkpoint
from crucis.persistence.policy import (
    OptimizerState,
    OptimizerStatus,
    load_active_policy,
    load_candidate_policy,
    load_optimizer_status,
    save_active_policy,
    save_optimizer_status,
)
from crucis.persistence.settings import (
    apply_agent_settings_to_env,
    load_runtime_settings,
    try_load_runtime_settings,
)

_STORE_TRUE = "store_true"
_WORKSPACE_FLAG = "--workspace"
_CHECKPOINT_FLAG = "--checkpoint"
_OBJECTIVE_FLAG = "--objective"
_PROFILES_FLAG = "--profiles"
_JSON_OPTION = "--json"
_JSON_ATTR = "json"
_WORKSPACE_ATTR = "workspace"
_OBJECTIVE_POS = "objective_path"
_OBJECTIVE_POS_HELP = "Path to objective YAML file"
_CHECKPOINT_HELP = "Path to checkpoint file (default: .checkpoint.json)"
_NO_CHECKPOINT_HINT = "Run `crucis run` first to generate test suites."
_HINT_INIT_OR_CHECK_PATH = "Check the path or run 'crucis init' to create one."
_JOIN_SEP = ", "
_TASKS_ATTR = "tasks"
_PROFILES_ATTR = "profiles"
_TASK_FLAG = "--task"
_DRY_RUN_ATTR = "dry_run"
_JSON_HELP = "Print machine-readable JSON output"
_MODEL_METAVAR = "MODEL"
_SEVERITY_KEY = "severity"
_SEVERITY_ERROR = "error"

_OPTIMIZER_EXPERIMENTAL_MSG = (
    "The optimizer is experimental and disabled by default. "
    "To enable, add 'optimizer:\\n  enabled: true' to .crucis/settings.yaml."
)


def _is_optimizer_enabled_for_command(workspace: Path) -> bool:
    """Check optimizer enabled status and print guidance when disabled.

    Args:
        workspace: Workspace root directory.

    Returns:
        True when optimizer is enabled.
    """
    from crucis.persistence.settings import is_optimizer_enabled

    if is_optimizer_enabled(workspace):
        return True
    display_info(_OPTIMIZER_EXPERIMENTAL_MSG)
    return False


def _load_optimizer_status_if_relevant(workspace: Path) -> "OptimizerStatus | None":
    """Load optimizer status only when optimizer is active or has state.

    Args:
        workspace: Workspace root directory.

    Returns:
        Optimizer status when relevant, None otherwise.
    """
    from crucis.persistence.settings import is_optimizer_enabled

    status = load_optimizer_status(workspace)
    if status is not None:
        return status
    if is_optimizer_enabled(workspace):
        return OptimizerStatus(state="idle")
    return None


def _get_version() -> str:
    """Return package version with fallback for editable/uninstalled setups.

    Returns:
        Version string.
    """
    try:
        from importlib.metadata import version

        return version("crucis")
    except Exception:
        return "dev"


_PROFILES_HELP = "Path to constraint profiles YAML (default: constraints/profiles.yaml)"
_WORKSPACE_HELP = "Workspace directory root"
_WORKSPACE_ARTIFACTS_HELP = "Workspace directory for artifacts (default: objective file's parent)"
_RESET_TASKS_DEST = "reset_tasks"
_ACTION_APPEND = "append"


def build_parser() -> argparse.ArgumentParser:
    """Build the Crucis CLI parser.

    Returns:
        Constructed argument parser with all subcommands.
    """
    parser = argparse.ArgumentParser(
        prog="crucis",
        description="Crucis: agentic test-driven development — generate, harden, and evaluate "
        "test suites using LLM agents.",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )
    color_group = parser.add_mutually_exclusive_group()
    color_group.add_argument("--color", action=_STORE_TRUE, help="Force colored output")
    color_group.add_argument("--no-color", action=_STORE_TRUE, help="Disable colored output")
    verbosity_group = parser.add_mutually_exclusive_group()
    verbosity_group.add_argument(
        "--verbose", action=_STORE_TRUE, help="Show all diagnostic details"
    )
    verbosity_group.add_argument(
        "--quiet", action=_STORE_TRUE, help="Suppress informational output"
    )
    subs = parser.add_subparsers(dest="command", required=True)
    _add_init_parser(subs)
    _add_run_parser(subs)
    _add_status_parser(subs)
    _add_validate_parser(subs)
    _add_doctor_parser(subs)
    _add_optimizer_worker_parser(subs)
    _add_promote_parser(subs)
    return parser


def _add_init_parser(subs) -> None:
    """Add the init subcommand to the parser.

    Args:
        subs: Subparsers action from the parent parser.
    """
    p = subs.add_parser(
        "init",
        help="Scaffold a new Crucis workspace",
        description="Requires Python 3.10+ (3.12+ recommended). Create starter workspace files "
        "(objective.yaml + src/solution.py). Use --with-profiles and --with-settings "
        "for advanced configuration. By default, an AI agent interviews you about your project.",
    )
    p.add_argument("--name", default="my_project", help="Project name for the objective template")
    p.add_argument(
        _WORKSPACE_FLAG,
        default=".",
        help="Directory to scaffold (default: current directory)",
    )
    p.add_argument(
        "--no-agent",
        action="store_true",
        help="Skip AI interview; use static templates (for CI/automation)",
    )
    p.add_argument(
        "--agent",
        default=None,
        choices=["claude", "codex"],
        help="Which agent conducts the onboarding (default: generation_agent from config)",
    )
    p.add_argument(
        "--require-agent",
        action=_STORE_TRUE,
        help="Fail init when agent onboarding cannot run or does not complete",
    )
    p.add_argument(
        "--existing-codebase",
        action=_STORE_TRUE,
        help=(
            "Treat workspace as an existing codebase (skip src/solution.py scaffolding). "
            "By default this is auto-detected when Python files already exist."
        ),
    )
    p.add_argument(
        "--with-profiles",
        action=_STORE_TRUE,
        help="Also generate constraints/profiles.yaml with default constraint profiles",
    )
    p.add_argument(
        "--with-settings",
        action=_STORE_TRUE,
        help="Also generate .crucis/settings.yaml with agent/optimizer configuration",
    )
    p.add_argument(_JSON_OPTION, action=_STORE_TRUE, help=_JSON_HELP)


def _add_run_parser(subs) -> None:
    """Add the run subcommand to the parser.

    Args:
        subs: Subparsers action from the parent parser.
    """
    p = subs.add_parser(
        "run",
        help="Run the full pipeline: generate test suites, harden, and implement",
        description="Generate test suites, run adversarial review, and implement code. "
        "Auto-finds objective.yaml in the current directory if not specified. "
        "By default, approves everything and runs the full pipeline.",
    )
    p.add_argument(_OBJECTIVE_POS, nargs="?", default=None, help=_OBJECTIVE_POS_HELP)
    p.add_argument(
        _OBJECTIVE_FLAG,
        dest="objective_flag",
        help="Path to objective YAML (alternative to positional argument)",
    )
    p.add_argument(
        _PROFILES_FLAG,
        default=DEFAULT_PROFILES_PATH,
        help=_PROFILES_HELP,
    )
    p.add_argument(
        _CHECKPOINT_FLAG,
        default=DEFAULT_CHECKPOINT_PATH,
        help=_CHECKPOINT_HELP,
    )
    p.add_argument(
        _WORKSPACE_FLAG,
        default=None,
        help=_WORKSPACE_ARTIFACTS_HELP,
    )
    p.add_argument(
        _TASK_FLAG,
        action=_ACTION_APPEND,
        dest=_TASKS_ATTR,
        help="Process only named task(s); repeatable",
    )
    p.add_argument(
        "--reset",
        action=_STORE_TRUE,
        help="Clear checkpoint state before starting (fresh run)",
    )
    p.add_argument(
        "--reset-task",
        action=_ACTION_APPEND,
        dest=_RESET_TASKS_DEST,
        help="Clear only named task(s) from checkpoint; repeatable",
    )
    p.add_argument(
        "--no-sandbox", action=_STORE_TRUE, help="Run pytest on host instead of Docker sandbox"
    )
    p.add_argument(
        "-y", "--yes", action=_STORE_TRUE, help="Skip confirmation prompts (e.g. --reset)"
    )
    p.add_argument(
        "--dry-run",
        action=_STORE_TRUE,
        help="Display generation prompts without calling agents",
    )
    p.add_argument(
        "--demo",
        action=_STORE_TRUE,
        help="Simulate the workflow with canned data (no API key required)",
    )
    p.add_argument(
        "--plan",
        action=_STORE_TRUE,
        help="Generate a structured plan.md instead of running the pipeline",
    )
    p.add_argument(
        "--force-plan",
        action=_STORE_TRUE,
        help="Regenerate plan.md even if it already exists (use with --plan)",
    )
    _add_run_agent_args(p)


def _add_run_agent_args(p: argparse.ArgumentParser) -> None:
    """Add agent, model, and performance flags to the run parser.

    Args:
        p: The run subcommand parser.
    """
    p.add_argument(
        "--timeout",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Override agent subprocess timeout (default: 300s)",
    )
    p.add_argument(
        "--model",
        default=None,
        metavar=_MODEL_METAVAR,
        help="Override all agent models (generation, critic, implementation)",
    )
    p.add_argument(
        "--generation-model",
        default=None,
        metavar=_MODEL_METAVAR,
        help="Override the test generation model",
    )
    p.add_argument(
        "--critic-model",
        default=None,
        metavar=_MODEL_METAVAR,
        help="Override the adversarial critic model",
    )
    p.add_argument(
        "--implementation-model",
        default=None,
        metavar=_MODEL_METAVAR,
        help="Override the implementation model",
    )
    p.add_argument(
        "--fast",
        action=_STORE_TRUE,
        help="Skip adversarial review and cheating probe (faster iteration)",
    )


def _add_status_parser(subs) -> None:
    """Add the status subcommand to the parser.

    Args:
        subs: Subparsers action from the parent parser.
    """
    p = subs.add_parser(
        "status",
        aliases=["summary"],
        help="Show progress and optimizer status",
        description="Display a table of per-task progress and background optimizer state.",
    )
    p.add_argument(
        _CHECKPOINT_FLAG,
        default=DEFAULT_CHECKPOINT_PATH,
        help=_CHECKPOINT_HELP,
    )
    p.add_argument(
        _TASK_FLAG,
        default=None,
        help="Show test source and adversarial report for a specific task",
    )
    p.add_argument(
        _JSON_OPTION,
        action=_STORE_TRUE,
        help="Print machine-readable progress JSON",
    )
    p.add_argument(_WORKSPACE_FLAG, default=None, help=_WORKSPACE_HELP)


def _add_validate_parser(subs) -> None:
    """Add the validate subcommand to the parser.

    Args:
        subs: Subparsers action from the parent parser.
    """
    p = subs.add_parser(
        "validate",
        help="Validate an objective file without running agents",
        description="Parse and validate an objective YAML file, reporting any errors.",
    )
    p.add_argument(_OBJECTIVE_POS, help=_OBJECTIVE_POS_HELP)
    p.add_argument(
        _PROFILES_FLAG,
        default=None,
        help="Optional profiles file to validate against",
    )
    p.add_argument(
        _WORKSPACE_FLAG,
        default=None,
        help="Workspace directory for resolving relative paths",
    )
    p.add_argument(
        "--static",
        action="store_true",
        default=False,
        help="Run only structural checks (skip LLM semantic review)",
    )
    p.add_argument(_JSON_OPTION, action=_STORE_TRUE, help=_JSON_HELP)


def _add_doctor_parser(subs) -> None:
    """Add the doctor subcommand to the parser.

    Args:
        subs: Subparsers action from the parent parser.
    """
    p = subs.add_parser(
        "doctor",
        help="Run environment and workspace diagnostics",
        description="Check runtime prerequisites, agent binaries, and optional workspace files.",
    )
    p.add_argument(_WORKSPACE_FLAG, default=".", help=_WORKSPACE_HELP)
    p.add_argument(_OBJECTIVE_FLAG, default=None, help="Optional objective file to validate")
    p.add_argument(_PROFILES_FLAG, default=None, help="Optional profiles file to validate")
    p.add_argument(_CHECKPOINT_FLAG, default=None, help="Optional checkpoint file to validate")
    p.add_argument(
        "--require-docker",
        action=_STORE_TRUE,
        help="Fail diagnostics when Docker sandbox is unavailable",
    )
    p.add_argument(
        "-v", "--verbose",
        action=_STORE_TRUE,
        help="Show all checks including passing ones (default: only warnings/failures)",
    )
    p.add_argument(_JSON_OPTION, action=_STORE_TRUE, help=_JSON_HELP)


def _add_optimizer_worker_parser(subs) -> None:
    """Add the optimizer-worker subcommand to the parser.

    Args:
        subs: Subparsers action from the parent parser.
    """
    p = subs.add_parser(
        "optimizer-worker",
        help=argparse.SUPPRESS,
        description="Run one queued optimizer drain pass by default, or continuous loop mode.",
    )
    p.add_argument(_WORKSPACE_FLAG, default=".", help=_WORKSPACE_HELP)
    p.add_argument(
        "--loop",
        action=_STORE_TRUE,
        help="Run continuously instead of one-shot processing",
    )
    p.add_argument(_JSON_OPTION, action=_STORE_TRUE, help=_JSON_HELP)



def _add_promote_parser(subs) -> None:
    """Add the promote subcommand to the parser.

    Args:
        subs: Subparsers action from the parent parser.
    """
    p = subs.add_parser(
        "promote",
        help=argparse.SUPPRESS,
        description="[Experimental] Replace the active optimizer policy with a winning candidate "
        "from a completed optimization run. Requires optimizer.enabled: true in settings.",
    )
    p.add_argument("--run-id", required=True, help="Run ID of candidate to promote")
    p.add_argument(_WORKSPACE_FLAG, default=".", help=_WORKSPACE_HELP)
    p.add_argument(
        "--force",
        action=_STORE_TRUE,
        help="Promote even when candidate-ready metadata is missing or mismatched",
    )
    p.add_argument(_JSON_OPTION, action=_STORE_TRUE, help=_JSON_HELP)


def show_checkpoint(checkpoint_path: Path, as_json: bool = False) -> None:
    """Load and display a persisted checkpoint table.

    Args:
        checkpoint_path: Path to the checkpoint JSON file.
    """
    resolved = checkpoint_path if checkpoint_path.is_absolute() else Path.cwd() / checkpoint_path
    try:
        state = load_checkpoint(resolved)
    except ValueError as exc:
        display_error(str(exc))
        raise SystemExit(1) from exc
    if state is None:
        display_error(f"No checkpoint found at {resolved}. {_NO_CHECKPOINT_HINT}")
        raise SystemExit(1)
    optimizer_status = _load_optimizer_status_if_relevant(resolved.parent)
    if as_json:
        print(json.dumps(_checkpoint_payload(state, resolved, optimizer_status), indent=2))
        return
    display_checkpoint_table(state, optimizer_status=optimizer_status)


def _show_task_detail(checkpoint_path: Path, task_name: str, as_json: bool = False) -> None:
    """Display detailed test source and adversarial report for one task.

    Args:
        checkpoint_path: Path to the checkpoint JSON file.
        task_name: Task name to look up in the checkpoint.
        as_json: Whether to print machine-readable JSON output.
    """
    resolved = checkpoint_path if checkpoint_path.is_absolute() else Path.cwd() / checkpoint_path
    try:
        state = load_checkpoint(resolved)
    except ValueError as exc:
        display_error(str(exc))
        raise SystemExit(1) from exc
    if state is None:
        display_error(f"No checkpoint found at {resolved}. {_NO_CHECKPOINT_HINT}")
        raise SystemExit(1)

    for progress in state.task_progress:
        if progress.name == task_name:
            if as_json:
                payload = {
                    "name": progress.name,
                    "status": progress.status.value,
                    "train_suite_source": progress.train_suite_source,
                    "adversarial_report": (
                        progress.adversarial_report.model_dump(mode="json")
                        if progress.adversarial_report is not None
                        else None
                    ),
                }
                print(json.dumps(payload, indent=2))
            else:
                if progress.train_suite_source:
                    display_test_suite_source(progress.train_suite_source)
                if progress.adversarial_report:
                    display_adversarial_report(progress.adversarial_report)
                if not progress.train_suite_source and not progress.adversarial_report:
                    display_info(f"Task '{task_name}' has no generated data yet.")
            return

    display_error(f"Task '{task_name}' not found in checkpoint.")
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    """Parse CLI args and dispatch to the appropriate command handler.

    Args:
        argv: Optional CLI arguments; defaults to process arguments when None.
    """
    raw_args = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw_args)
    configure_console(
        no_color=bool(getattr(args, "no_color", False)),
        force_color=bool(getattr(args, "color", False)),
    )
    handlers = {
        "init": run_init_command,
        "run": _handle_run_command,
        "status": _handle_status_command,
        "validate": run_validate_command,
        "doctor": run_doctor_command,
        "optimizer-worker": run_optimizer_worker_command,
        "promote": run_promote,
    }
    handler = handlers.get(args.command)
    if handler is None:
        return
    handler(args)


def _resolve_objective_path(
    args: argparse.Namespace, command: str, check_exists: bool = False
) -> Path:
    """Resolve and validate objective path from positional/flag args.

    Args:
        args: Parsed CLI arguments object.
        command: Command name for usage hint.
        check_exists: Whether to verify the file exists on disk.

    Returns:
        Validated objective path.
    """
    positional = getattr(args, _OBJECTIVE_POS, None)
    flag = getattr(args, "objective_flag", None) or getattr(args, "objective", None)
    if positional and flag and positional != flag:
        display_error(
            f"Conflicting objective paths: positional '{positional}' vs --objective '{flag}'. "
            "Provide only one."
        )
        raise SystemExit(2)
    raw_path = positional or flag
    if not raw_path:
        default_objective = Path.cwd() / "objective.yaml"
        if default_objective.exists():
            raw_path = str(default_objective)
        else:
            display_error(
                f"No objective file specified and no objective.yaml in current directory. "
                f"Usage: crucis {command} <objective.yaml>",
                hint=_HINT_INIT_OR_CHECK_PATH,
            )
            raise SystemExit(2)
    objective_path = Path(raw_path)
    if check_exists and not objective_path.exists():
        display_error(
            f"Objective file not found: {objective_path}",
            hint=_HINT_INIT_OR_CHECK_PATH,
        )
        raise SystemExit(1)
    return objective_path


_DEMO_TEST = """\
import pytest

def test_add_basic():
    assert add(1, 2) == 3

def test_add_zero():
    assert add(0, 5) == 5

def test_add_negative():
    assert add(-1, -2) == -3
"""

_DEMO_REPORT = AdversarialReport(
    attack_vectors=["hardcoded return value", "swapped argument order"],
    generalization_gaps=["large integers", "floating-point inputs"],
    suggested_probe_tests=["test with float args", "test commutativity"],
    correctness_issues=[],
)


def _run_demo_fit(
    objective_path: Path, profiles_path: Path, workspace: Path
) -> None:
    """Simulate the fit workflow with canned data, no API calls.

    Args:
        objective_path: Path to the objective YAML file.
        profiles_path: Path to the constraint profiles YAML file.
        workspace: Workspace root directory.
    """
    from crucis.models import CheckpointState, TaskProgress, TrainingStatus

    objective = parse_objective(objective_path)
    tasks = objective.tasks or [objective]
    display_workspace(workspace)
    display_info("[demo mode — no agents will be called]\n")

    progress_list = []
    for idx, task in enumerate(tasks, 1):
        display_task_header(task.name, index=idx, total=len(tasks))
        display_test_suite_source(_DEMO_TEST)
        display_hardening_cycle(task.name, 1, 1)
        display_adversarial_report(_DEMO_REPORT)
        progress_list.append(
            TaskProgress(name=task.name, status=TrainingStatus.complete)
        )

    state = CheckpointState(task_progress=progress_list)
    display_fit_complete(state)
    display_success("Demo complete — no agents were called. Remove --demo to run for real.")


def _apply_reset(
    checkpoint_path: Path,
    reset_all: bool,
    reset_tasks: list[str],
    skip_confirm: bool = False,
) -> None:
    """Apply checkpoint reset before a fit run.

    Args:
        checkpoint_path: Path to the checkpoint file.
        reset_all: When True, delete the entire checkpoint.
        reset_tasks: Task names to reset individually.
        skip_confirm: When True, skip interactive confirmation prompt.
    """
    if reset_all:
        if checkpoint_path.exists():
            if not skip_confirm and _is_interactive_terminal():
                answer = prompt_input("[bold yellow]This will delete the checkpoint.[/bold yellow] Continue? [y/N] ").lower()
                if answer not in ("y", "yes"):
                    display_info("Reset cancelled.")
                    return
            checkpoint_path.unlink()
            display_info("Checkpoint cleared.")
        return
    if not reset_tasks or not checkpoint_path.exists():
        return
    state = load_checkpoint(checkpoint_path)
    if state is None:
        return
    for task in state.task_progress:
        if task.name in reset_tasks:
            task.status = TrainingStatus.pending
            task.train_suite_source = None
            task.adversarial_report = None
    save_checkpoint(state, checkpoint_path)
    display_info(f"Reset task(s): {', '.join(reset_tasks)}")


def _fit_preflight(
    config: Config,
    effective_workspace: Path,
    auto_evaluate: bool,
) -> None:
    """Run fail-fast preflight checks for fit command.

    Args:
        config: Runtime configuration values.
        effective_workspace: Resolved workspace directory.
        auto_evaluate: Whether evaluation auto-runs after fit.
    """
    require_pytest = auto_evaluate and not check_docker_available()
    required_agents = {config.generation_agent, config.critic_agent}
    if auto_evaluate:
        required_agents.add(config.implementation_agent)
    _run_preflight_or_exit(
        workspace=effective_workspace,
        config=config,
        required_agents=required_agents,
        require_pytest=require_pytest,
    )


def _auto_clear_empty_checkpoint(checkpoint_path: Path) -> None:
    """Silently remove a checkpoint where all tasks are still pending.

    Args:
        checkpoint_path: Path to the checkpoint file.
    """
    if not checkpoint_path.exists():
        return
    state = load_checkpoint(checkpoint_path)
    if state is None:
        return
    if all(t.status == TrainingStatus.pending for t in state.task_progress):
        checkpoint_path.unlink()


def _resolve_fit_reset(args: argparse.Namespace, checkpoint_path: Path) -> list[str] | None:
    """Validate and apply reset flags, returning resolved task_names.

    Args:
        args: Parsed CLI arguments object.
        checkpoint_path: Path to the checkpoint file.

    Returns:
        Task names to process, or None for all tasks.
    """
    _auto_clear_empty_checkpoint(checkpoint_path)
    reset_all = bool(getattr(args, "reset", False))
    reset_tasks = getattr(args, "reset_tasks", None) or []
    if reset_all and reset_tasks:
        display_error(
            "Cannot use --reset together with --reset-task.",
            hint="Use only one of these flags.",
        )
        raise SystemExit(2)
    skip_confirm = bool(getattr(args, "yes", False))
    _apply_reset(checkpoint_path, reset_all, reset_tasks, skip_confirm=skip_confirm)
    task_names = getattr(args, _TASKS_ATTR, None)
    if reset_tasks and not task_names:
        task_names = list(reset_tasks)
    return task_names


def _apply_model_overrides(args: argparse.Namespace) -> None:
    """Set model env vars from CLI flags before Config() reads them.

    Per-step flags (``--generation-model`` etc.) override ``--model``.

    Args:
        args: Parsed CLI arguments with model override fields.
    """
    base = getattr(args, "model", None)
    gen = getattr(args, "generation_model", None)
    critic = getattr(args, "critic_model", None)
    impl = getattr(args, "implementation_model", None)
    if base:
        os.environ["GENERATION_MODEL"] = base
        os.environ["CRITIC_MODEL"] = base
        os.environ["IMPLEMENTATION_MODEL"] = base
    if gen:
        os.environ["GENERATION_MODEL"] = gen
    if critic:
        os.environ["CRITIC_MODEL"] = critic
    if impl:
        os.environ["IMPLEMENTATION_MODEL"] = impl


def _handle_run_command(args: argparse.Namespace) -> None:
    """Execute the unified run pipeline.

    Handles three modes:
    - ``--plan``: generate a structured plan.md
    - ``--dry-run``: preview generation prompts without calling agents
    - Default: full pipeline (fit + evaluate), auto-approve everything

    Args:
        args: Parsed CLI arguments object.
    """
    if bool(getattr(args, "plan", False)):
        _handle_run_plan(args)
        return

    args.auto = True
    args.auto_tests = True
    args.auto_adversary = True
    args.evaluate = not bool(getattr(args, _DRY_RUN_ATTR, False))
    _handle_fit_command(args)


def _handle_fit_command(args: argparse.Namespace) -> None:
    """Execute fit command preflight and dispatch.

    Args:
        args: Parsed CLI arguments object.
    """
    objective_path = _resolve_objective_path(args, "run", check_exists=True)
    ws_arg = getattr(args, _WORKSPACE_ATTR, None)
    workspace = Path(ws_arg).resolve() if ws_arg else None
    effective_workspace = workspace or objective_path.parent
    _ensure_runtime_settings(effective_workspace)
    _apply_model_overrides(args)

    if bool(getattr(args, "demo", False)):
        _run_demo_fit(objective_path, Path(args.profiles), effective_workspace)
        return

    dry_run = bool(getattr(args, _DRY_RUN_ATTR, False))
    config = Config()
    auto_evaluate = bool(getattr(args, "evaluate", False)) if not dry_run else False
    if not dry_run:
        _fit_preflight(config, effective_workspace, auto_evaluate)

    checkpoint_path = Path(args.checkpoint)
    if not checkpoint_path.is_absolute():
        checkpoint_path = effective_workspace / checkpoint_path
    task_names = _resolve_fit_reset(args, checkpoint_path)

    auto_all = bool(getattr(args, "auto", False))
    fit_kwargs: dict = dict(
        objective_path=objective_path,
        profiles_path=Path(args.profiles),
        checkpoint_path=checkpoint_path,
        auto_tests=auto_all or bool(getattr(args, "auto_tests", False)),
        auto_adversary=auto_all or bool(getattr(args, "auto_adversary", False)),
        auto_evaluate=auto_evaluate,
        workspace=workspace,
        no_sandbox=bool(getattr(args, "no_sandbox", False)),
    )
    if dry_run:
        fit_kwargs[_DRY_RUN_ATTR] = True
    if task_names:
        fit_kwargs["task_names"] = task_names
    agent_timeout = getattr(args, "timeout", None)
    if agent_timeout is not None:
        fit_kwargs["agent_timeout"] = agent_timeout
    if bool(getattr(args, "fast", False)):
        fit_kwargs["skip_hardening"] = True
    try:
        run_fit(**fit_kwargs)
    except (ValueError, RuntimeError) as exc:
        display_error(str(exc))
        raise SystemExit(1) from exc


def _handle_run_plan(args: argparse.Namespace) -> None:
    """Handle ``run --plan`` by generating a structured plan.md.

    Args:
        args: Parsed CLI arguments object.
    """
    objective_path = _resolve_objective_path(args, "run --plan", check_exists=True)
    ws_arg = getattr(args, _WORKSPACE_ATTR, None)
    workspace = Path(ws_arg).resolve() if ws_arg else objective_path.parent
    _ensure_runtime_settings(workspace)

    plan_path = workspace / "plan.md"
    force = bool(getattr(args, "force_plan", False))
    if plan_path.exists() and not force:
        display_error(f"Plan already exists at {plan_path}. Use --force-plan to regenerate.")
        raise SystemExit(1)

    objective = parse_objective(objective_path)
    profiles = load_profiles(_resolve_plan_profiles(workspace, Path(args.profiles)))
    effective_tasks = objective.tasks or [objective]
    constraints_map = {
        task.name: resolve_constraints(objective, profiles, task.name) for task in effective_tasks
    }

    config = Config()
    model_label = config.generation_model or "default model"
    display_info(f"Generating plan with {config.generation_agent} ({model_label})...")
    try:
        plan_content = build_generation_plan(objective, constraints_map, config)
    except (RuntimeError, ValueError) as exc:
        display_error(str(exc), hint="Verify agent availability with 'crucis doctor'.")
        raise SystemExit(1) from exc
    created = write_plan_to_workspace(plan_content, workspace)
    display_success(f"  Created: {created}")
    display_info("\nRun `crucis run` to use this plan during generation.")


def _handle_status_command(args: argparse.Namespace) -> None:
    """Execute summary display command.

    Args:
        args: Parsed CLI arguments object.
    """
    checkpoint_path = Path(args.checkpoint)
    ws_arg = getattr(args, _WORKSPACE_ATTR, None)
    if ws_arg and not checkpoint_path.is_absolute():
        checkpoint_path = Path(ws_arg).resolve() / checkpoint_path
    task_name = getattr(args, "task", None)
    as_json = bool(getattr(args, _JSON_ATTR, False))
    if task_name:
        _show_task_detail(checkpoint_path, task_name, as_json=as_json)
    else:
        show_checkpoint(checkpoint_path, as_json=as_json)


def _validate_profiles(objective: "ParsedObjective", profiles_path: str) -> None:
    """Validate that the referenced constraint profile exists.

    Args:
        objective: Parsed objective to check.
        profiles_path: Path to the profiles YAML file.
    """
    try:
        profiles = load_profiles(Path(profiles_path))
    except ValueError as exc:
        display_error(str(exc))
        raise SystemExit(1) from exc
    profile_name = objective.tests_constraint_profile or "default"
    available = sorted(k for k in profiles if k != _TASKS_ATTR)
    if profile_name not in profiles:
        display_error(
            f"Objective references profile '{profile_name}' "
            f"which is not in {profiles_path}. Available: {_JOIN_SEP.join(available)}"
        )
        raise SystemExit(1)
    display_success(f"  Profiles file valid. Available: {_JOIN_SEP.join(available)}")



def _has_error_severity(issues: list[dict]) -> bool:
    """Check whether any issue has error severity.

    Args:
        issues: List of issue dicts from the LLM review.

    Returns:
        True when at least one issue has severity 'error'.
    """
    return any(i.get(_SEVERITY_KEY) == _SEVERITY_ERROR for i in issues)


def _validate_error_exit(message: str, as_json: bool) -> None:
    """Display an error and exit with code 1.

    Args:
        message: Error message to display.
        as_json: When True, emit JSON instead of Rich output.
    """
    if as_json:
        print(json.dumps({"valid": False, _SEVERITY_ERROR: message}))
    else:
        display_error(message)


def run_validate_command(args: argparse.Namespace) -> None:
    """Validate an objective file and optionally its profiles.

    Args:
        args: Parsed CLI arguments object.
    """
    as_json = bool(getattr(args, _JSON_ATTR, False))
    ws = Path(args.workspace).resolve() if getattr(args, _WORKSPACE_ATTR, None) else None
    raw_path = Path(args.objective_path)
    objective_path = (ws / raw_path) if ws and not raw_path.is_absolute() else raw_path
    try:
        objective = parse_objective(objective_path)
    except ValueError as exc:
        _validate_error_exit(str(exc), as_json)
        raise SystemExit(1) from exc

    issues: list[dict] = []
    if not getattr(args, "static", False):
        config = Config()
        try:
            issues = review_objective_semantics(
                objective,
                agent=config.critic_agent,
                model=config.critic_model,
                budget=config.max_budget_usd,
            )
        except RuntimeError as exc:
            _validate_error_exit(str(exc), as_json)
            raise SystemExit(1) from exc

    if as_json:
        print(json.dumps({
            "name": objective.name,
            "tasks": [t.name for t in objective.tasks],
            "valid": not _has_error_severity(issues),
            "issues": issues,
        }))
    else:
        display_success(f"Objective '{objective.name}' is valid.")
        display_info(f"  Tasks: {len(objective.tasks)}")
        for task in objective.tasks:
            display_info(f"    - {task.name}")
        profiles_path = getattr(args, _PROFILES_ATTR, None)
        if profiles_path:
            _validate_profiles(objective, profiles_path)
        if issues:
            display_validation_report(issues)

    if _has_error_severity(issues):
        raise SystemExit(1)


def run_evaluate(
    objective_path: Path,
    profiles_path: Path,
    checkpoint_path: Path,
    use_sandbox: bool = True,
    workspace: Path | None = None,
) -> None:
    """Load a checkpoint and run the evaluation agent.

    Args:
        objective_path: Path to the objective YAML file.
        profiles_path: Path to the constraint profiles YAML file.
        checkpoint_path: Path to the checkpoint JSON file.
        use_sandbox: Whether verification runs inside the Docker sandbox.
        workspace: Workspace directory for artifacts; defaults to objective's parent.
    """
    workspace = workspace or objective_path.parent
    _ensure_runtime_settings(workspace)
    if profiles_path.is_absolute():
        effective_profiles_path = profiles_path.resolve()
    else:
        workspace_relative = workspace / profiles_path
        effective_profiles_path = (
            workspace_relative.resolve()
            if workspace_relative.exists()
            else profiles_path.resolve()
        )
    active_policy = _load_policy_or_none(workspace)

    try:
        objective = parse_objective(objective_path)
    except ValueError as exc:
        display_error(
            f"Invalid objective '{objective_path}': {exc}",
            hint=_HINT_INIT_OR_CHECK_PATH,
        )
        raise SystemExit(1) from exc

    if not checkpoint_path.is_absolute():
        checkpoint_path = workspace / checkpoint_path

    try:
        state = load_checkpoint(checkpoint_path)
    except ValueError as exc:
        display_error(str(exc))
        raise SystemExit(1) from exc
    if state is None:
        display_error(f"No checkpoint found at {checkpoint_path.resolve()}. {_NO_CHECKPOINT_HINT}")
        raise SystemExit(1)

    try:
        profiles = load_profiles(effective_profiles_path)
    except ValueError as exc:
        display_error(str(exc))
        raise SystemExit(1) from exc
    config = Config()

    if use_sandbox:
        available = check_docker_available()
        display_sandbox_status(available)
        if not available:
            use_sandbox = False

    constraints_map = {
        progress.name: resolve_constraints(objective, profiles, progress.name, scope="tests")
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
        policy=active_policy,
        profiles_path=effective_profiles_path,
    )
    if passed:
        state.evaluation_passed = True
        save_checkpoint(state, checkpoint_path)
    if not passed:
        raise SystemExit(1)



def run_promote(args: argparse.Namespace) -> None:
    """Promote one optimizer candidate policy into active policy.

    Args:
        args: Parsed CLI arguments object.
    """
    workspace = Path(args.workspace).resolve()
    if not _is_optimizer_enabled_for_command(workspace):
        return
    run_id = str(args.run_id)
    force = bool(getattr(args, "force", False))

    status = load_optimizer_status(workspace)
    if not force:
        if status is None:
            display_error(
                "No optimizer status found for this workspace. "
                "Run `crucis status` to discover candidate-ready runs or use "
                "`crucis promote --run-id <id> --force`."
            )
            raise SystemExit(1)
        if not status.candidate_ready or status.candidate_run_id != run_id:
            display_error(
                f"Run `{run_id}` is not marked candidate-ready for promotion. "
                "Use the candidate shown by `crucis status` or pass --force "
                "to override."
            )
            raise SystemExit(1)

    try:
        candidate = load_candidate_policy(workspace, run_id)
    except FileNotFoundError as exc:
        display_error(str(exc))
        raise SystemExit(1) from exc
    except Exception as exc:
        display_error(f"Could not load candidate policy: {exc}")
        raise SystemExit(1) from exc

    save_active_policy(candidate, workspace)
    next_status = status or OptimizerStatus()
    next_status.state = OptimizerState.completed
    next_status.last_run_id = run_id
    next_status.promoted = True
    next_status.active_policy_version = run_id
    next_status.candidate_ready = False
    next_status.candidate_run_id = None
    next_status.message = f"promoted candidate from run {run_id}"
    next_status.updated_at = datetime.now(UTC).isoformat()
    save_optimizer_status(workspace, next_status)
    if bool(getattr(args, _JSON_ATTR, False)):
        print(json.dumps({"run_id": run_id, "promoted": True}))
    else:
        display_success(f"Promoted candidate policy from run {run_id}.")


def _is_interactive_terminal() -> bool:
    """Return True when both stdin and stderr are attached to a TTY.

    Returns:
        True if both stdin and stderr are TTYs.
    """
    return bool(sys.stdin.isatty() and sys.stderr.isatty())


_RECOMMENDED_PYTHON = (3, 12)
_MINIMUM_PYTHON = (3, 10)


def _warn_if_unsupported_python() -> None:
    """Print an explicit warning when running on a non-recommended interpreter."""
    current = sys.version_info
    version_tuple = (current.major, current.minor)
    if version_tuple >= _RECOMMENDED_PYTHON:
        return
    label = f"Python {current.major}.{current.minor}.{current.micro}"
    if version_tuple >= _MINIMUM_PYTHON:
        display_warning(f"{label} is supported but Python 3.12+ is recommended.")
    else:
        display_warning(f"{label} is unsupported. Crucis requires Python 3.10+.")


def run_init_command(args: argparse.Namespace) -> None:
    """Scaffold a new Crucis workspace with starter files.

    Args:
        args: Parsed CLI arguments object.
    """
    _warn_if_unsupported_python()

    workspace = Path(args.workspace).resolve()
    no_agent = bool(getattr(args, "no_agent", False))
    require_agent = bool(getattr(args, "require_agent", False))
    forced_existing_codebase = bool(getattr(args, "existing_codebase", False))

    if no_agent and require_agent:
        display_error(
            "Cannot use --no-agent together with --require-agent.",
            hint="Use only one of these flags.",
        )
        raise SystemExit(2)

    from crucis.intake.scaffold import prompt_model_selection

    agent_choice, model_choice = (None, None) if no_agent else prompt_model_selection()

    already_initialized = _workspace_has_files(workspace)
    if already_initialized and agent_choice is not None:
        _update_settings_model(workspace, agent_choice, model_choice)
        return

    if not no_agent and not already_initialized:
        if _try_agent_onboarding(workspace, args, agent_choice, model_choice):
            return
        if require_agent:
            display_error(
                "Agent onboarding is required but did not complete.",
                hint="Retry or pass '--no-agent' to use static templates.",
            )
            raise SystemExit(1)

    name = str(getattr(args, "name", "my_project"))
    existing_codebase = forced_existing_codebase or detect_existing_codebase(workspace)
    include_settings = bool(getattr(args, "with_settings", False)) or agent_choice is not None
    created = scaffold_workspace(
        workspace, name=name, existing_codebase=existing_codebase,
        agent=agent_choice, model=model_choice,
        include_profiles=bool(getattr(args, "with_profiles", False)),
        include_settings=include_settings,
    )
    as_json = bool(getattr(args, _JSON_ATTR, False))
    _display_init_result(workspace, created, existing_codebase, as_json)


def _display_init_result(
    workspace: Path,
    created: list[Path],
    existing_codebase: bool,
    as_json: bool,
) -> None:
    """Display scaffold results in human-readable or JSON format.

    Args:
        workspace: Workspace root directory.
        created: List of created file paths (empty if nothing new).
        existing_codebase: Whether the workspace was treated as existing codebase.
        as_json: When True, emit JSON instead of Rich output.
    """
    payload = {
        "workspace": str(workspace),
        "created": [str(p) for p in created],
        "existing_codebase": existing_codebase,
    }
    if as_json:
        print(json.dumps(payload))
        return
    if not created:
        display_info("Workspace already initialized (all files exist).")
        return
    if existing_codebase:
        display_info(
            "Existing codebase detected. "
            "Objective scaffold skips src/solution.py and leaves target_files for you to set."
        )
    for path in created:
        display_info(f"  Created: {path}")
    _print_next_steps(workspace, existing_codebase=existing_codebase)


def _try_agent_onboarding(
    workspace: Path,
    args: argparse.Namespace,
    agent_override: str | None = None,
    model_override: str | None = None,
) -> bool:
    """Attempt agent-driven onboarding, returning True on success.

    Args:
        workspace: Target workspace directory.
        args: Parsed CLI arguments with optional --agent flag.
        agent_override: Agent name from interactive prompt, or None.
        model_override: Model name from interactive prompt, or None.

    Returns:
        True when the agent completed and generated valid files.
    """
    import shutil

    from crucis.config import Config
    from crucis.intake.scaffold import run_agent_onboarding, validate_onboarding_output

    config = Config()
    agent = getattr(args, "agent", None) or agent_override or config.generation_agent
    model = model_override or config.generation_model
    require_agent = bool(getattr(args, "require_agent", False))

    if not _is_interactive_terminal():
        message = (
            "Agent onboarding requires an interactive terminal. "
            "Re-run in an interactive shell, or pass --no-agent to scaffold static templates."
        )
        if require_agent:
            display_error(message)
            raise SystemExit(1)
        display_info("Non-interactive terminal detected. Skipping agent onboarding and using static templates.")
        return False

    if shutil.which(agent) is None:
        message = f"Agent '{agent}' not found on PATH."
        if require_agent:
            display_error(
                f"{message} Install it, remove --require-agent, or pass --no-agent."
            )
            raise SystemExit(1)
        display_info(f"{message} Using static templates.")
        return False

    success = run_agent_onboarding(workspace, agent, model)
    if not success:
        message = "Agent onboarding did not complete."
        if require_agent:
            display_error(f"{message} Remove --require-agent or pass --no-agent.")
            raise SystemExit(1)
        display_info(f"{message} Using static templates.")
        return False

    if not validate_onboarding_output(workspace):
        message = "Agent output is incomplete or invalid."
        if require_agent:
            display_error(f"{message} Remove --require-agent or pass --no-agent.")
            raise SystemExit(1)
        display_info(f"{message} Using static templates.")
        return False

    _print_next_steps(workspace)
    return True


def _workspace_has_files(workspace: Path) -> bool:
    """Check whether the workspace already has crucis files.

    Args:
        workspace: Workspace root directory.

    Returns:
        True when objective.yaml exists.
    """
    return (workspace / "objective.yaml").exists()


def _update_settings_model(
    workspace: Path, agent: str, model: str | None,
) -> None:
    """Update agent/model fields in an existing settings.yaml.

    Args:
        workspace: Workspace root directory.
        agent: Agent name to set.
        model: Model name to set.
    """
    from crucis.intake.scaffold import _render_settings_template
    from crucis.persistence.settings import settings_path

    path = settings_path(workspace)
    path.write_text(_render_settings_template(agent, model), encoding="utf-8")
    display_success(f"Updated settings: agent={agent}, model={model}")


def _print_next_steps(workspace: Path, existing_codebase: bool = False) -> None:
    """Print post-init guidance.

    Args:
        workspace: Workspace root directory.
        existing_codebase: Whether init scaffold was generated for an existing repository.
    """
    display_success(f"\nWorkspace ready at {workspace}")
    if not (workspace / ".git").is_dir():
        display_warning("run `git init` — codex requires a trusted git repository.")
    if existing_codebase:
        display_info(
            "Update objective.yaml target_files/context_files "
            "to point at existing project modules."
        )
    display_info("Next steps:")
    display_info("  crucis run                    # run the full pipeline")
    display_info("  crucis run --plan             # generate a structured plan first")
    display_info("  crucis run --task <name>      # process a single task")
    display_info("  crucis run --dry-run          # preview generation prompts")



def _resolve_plan_profiles(workspace: Path, profiles_path: Path) -> Path:
    """Resolve profiles path for plan command.

    Args:
        workspace: Workspace root directory.
        profiles_path: Profiles path from CLI argument.

    Returns:
        Resolved profiles path.
    """
    if profiles_path.is_absolute():
        return profiles_path.resolve()
    workspace_relative = workspace / profiles_path
    if workspace_relative.exists():
        return workspace_relative.resolve()
    return profiles_path.resolve()


def run_doctor_command(args: argparse.Namespace) -> None:
    """Run diagnostics command and print text or JSON report.

    Args:
        args: Parsed CLI arguments object.
    """
    workspace = Path(args.workspace).resolve()
    ws_settings = try_load_runtime_settings(workspace)
    if ws_settings is not None:
        apply_agent_settings_to_env(ws_settings)
    report = run_doctor(
        workspace=workspace,
        objective_path=Path(args.objective) if getattr(args, "objective", None) else None,
        profiles_path=Path(args.profiles) if getattr(args, _PROFILES_ATTR, None) else None,
        checkpoint_path=Path(args.checkpoint) if getattr(args, "checkpoint", None) else None,
        require_docker=bool(getattr(args, "require_docker", False)),
        config=Config(),
    )
    if bool(getattr(args, _JSON_ATTR, False)):
        print(json.dumps(doctor_report_payload(report), indent=2))
    else:
        verbose = bool(getattr(args, "verbose", False))
        display_doctor_report(report, verbose=verbose)
    if not report.ok:
        raise SystemExit(1)


def run_optimizer_worker_command(args: argparse.Namespace) -> None:
    """Run foreground optimizer worker for automation/integration use.

    Args:
        args: Parsed CLI arguments object.
    """
    workspace = Path(args.workspace).resolve()
    if not _is_optimizer_enabled_for_command(workspace):
        return
    loop_mode = bool(getattr(args, "loop", False))
    exit_code = run_optimizer_worker(workspace, once=not loop_mode)
    if not bool(getattr(args, _JSON_ATTR, False)) and exit_code == 0 and not loop_mode:
        display_info("Optimizer worker: no pending jobs. Nothing to do.")
    if bool(getattr(args, _JSON_ATTR, False)):
        print(
            json.dumps(
                {
                    "workspace": str(workspace),
                    "mode": "loop" if loop_mode else "once",
                    "exit_code": exit_code,
                },
                indent=2,
            )
        )
    if exit_code != 0:
        raise SystemExit(exit_code)



def _ensure_runtime_settings(workspace: Path) -> None:
    """Ensure runtime settings exist and apply agent config to environment.

    Agent settings from YAML are exported as env vars (when not already set)
    so that ``Config(BaseSettings)`` picks them up.

    Args:
        workspace: Workspace root directory.
    """
    try:
        settings = load_runtime_settings(workspace)
    except Exception as exc:
        display_error(f"Could not load runtime settings: {exc}")
        raise SystemExit(1) from exc
    apply_agent_settings_to_env(settings)


def _run_preflight_or_exit(
    workspace: Path,
    config: Config,
    required_agents: set[str],
    require_pytest: bool,
) -> None:
    """Run fail-fast prerequisite checks and exit with actionable errors.

    Args:
        workspace: Workspace root directory.
        config: Runtime configuration values.
        required_agents: Agent binaries required for this command path.
        require_pytest: Whether host pytest module is required.
    """
    checks = collect_preflight_checks(
        workspace=workspace,
        config=config,
        required_agents=required_agents,
        require_pytest=require_pytest,
    )
    failures = [check for check in checks if check.status == "fail"]
    if not failures:
        return
    for check in failures:
        detail = f" [{check.id}] {check.message}"
        if check.hint:
            detail += f" Hint: {check.hint}"
        display_error(detail)
    raise SystemExit(1)



def _checkpoint_payload(state, checkpoint_path: Path, optimizer_status) -> dict:
    """Build machine-readable checkpoint JSON payload.

    Args:
        state: Loaded checkpoint state.
        checkpoint_path: Resolved checkpoint path.
        optimizer_status: Optional optimizer status payload.

    Returns:
        Machine-readable checkpoint summary payload.
    """
    complete_count = sum(
        1 for progress in state.task_progress if progress.status.value == "complete"
    )
    total_count = len(state.task_progress)
    tasks = []
    for progress in state.task_progress:
        tasks.append(
            {
                "name": progress.name,
                "status": progress.status.value,
                "has_train_suite": bool(progress.train_suite_source),
                "has_adversarial_report": progress.adversarial_report is not None,
            }
        )
    return {
        "checkpoint_path": str(checkpoint_path),
        "workspace": str(checkpoint_path.parent),
        "summary": {
            "total_tasks": total_count,
            "complete_tasks": complete_count,
            "ready_for_evaluation": total_count > 0 and complete_count == total_count,
        },
        "tasks": tasks,
        "optimizer_status": (
            optimizer_status.model_dump(mode="json") if optimizer_status is not None else None
        ),
    }


def _load_policy_or_none(workspace: Path):
    """Load active policy with graceful fallback on invalid data.

    Args:
        workspace: Workspace root directory.

    Returns:
        Result of `_load_policy_or_none`.
    """
    try:
        return load_active_policy(workspace)
    except Exception as exc:
        display_error(f"Could not load active optimizer policy: {exc}")
        return None


if __name__ == "__main__":
    main()
