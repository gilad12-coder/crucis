"""CLI entry point for Crucis."""

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from crucis.config import Config
from crucis.constraints.loader import load_profiles, resolve_constraints
from crucis.core.loop import run_evaluation, run_fit
from crucis.core.planner import build_generation_plan, write_plan_to_workspace
from crucis.defaults import DEFAULT_CHECKPOINT_PATH, DEFAULT_PROFILES_PATH
from crucis.diagnostics import collect_preflight_checks, doctor_report_payload, run_doctor
from crucis.display import (
    display_adversarial_report,
    display_checkpoint_table,
    display_error,
    display_evaluation_result,
    display_fit_complete,
    display_hardening_cycle,
    display_sandbox_status,
    display_task_header,
    display_train_suite_source,
    display_workspace,
)
from crucis.models import AdversarialReport
from crucis.execution.optimizer import run_optimizer_worker
from crucis.execution.sandbox import check_docker_available
from crucis.intake.migration import migrate_checkpoint_file, migrate_objective_file
from crucis.intake.objective import parse_objective
from crucis.intake.scaffold import scaffold_workspace
from crucis.persistence.checkpoint import load_checkpoint
from crucis.persistence.policy import (
    OptimizerState,
    OptimizerStatus,
    load_active_policy,
    load_candidate_policy,
    load_optimizer_status,
    save_active_policy,
    save_optimizer_status,
)
from crucis.persistence.settings import apply_agent_settings_to_env, load_runtime_settings

_STORE_TRUE = "store_true"
_WORKSPACE_FLAG = "--workspace"
_CHECKPOINT_FLAG = "--checkpoint"
_OBJECTIVE_FLAG = "--objective"
_PROFILES_FLAG = "--profiles"
_JSON_OPTION = "--json"
_JSON_ATTR = "json"
_OBJECTIVE_POS = "objective_path"
_OBJECTIVE_POS_HELP = "Path to objective YAML file"
_CHECKPOINT_HELP = "Path to checkpoint file (default: .checkpoint.json)"
_NO_CHECKPOINT_HINT = "Run `crucis fit <objective.yaml>` first to generate test suites."
_MAX_PROFILE_KEYS_SHOWN = 3
_JOIN_SEP = ", "
_TASKS_ATTR = "tasks"
_PROFILES_ATTR = "profiles"
_TRAIN_EVALS_KEY = "train_evals"
_TASK_FLAG = "--task"
_TEXT_ENCODING = "utf-8"
_JSON_HELP = "Print machine-readable JSON output"
_EVALUATE_CMD = "evaluate"

_LEGACY_COMMANDS = {
    "run": "fit",
    "implement": _EVALUATE_CMD,
    "status": "checkpoint",
    "preview": "fit <objective.yaml> --dry-run",
}

_LEGACY_FLAGS = {
    "--session": "--checkpoint",
    "--implement": "--evaluate",
    "--auto-critique": "--auto-adversary",
    "--no-docker": "--no-sandbox",
    "--spec": "--objective",
}


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
    subs = parser.add_subparsers(dest="command", required=True)
    _add_init_parser(subs)
    _add_plan_parser(subs)
    _add_fit_parser(subs)
    _add_evaluate_parser(subs)
    _add_checkpoint_parser(subs)
    _add_show_parser(subs)
    _add_add_task_parser(subs)
    _add_add_eval_parser(subs)
    _add_validate_parser(subs)
    _add_profiles_parser(subs)
    _add_doctor_parser(subs)
    _add_optimizer_worker_parser(subs)
    _add_migrate_parser(subs)
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
        description="Create starter objective.yaml, constraints/profiles.yaml, "
        "and .crucis/settings.yaml in the target directory. "
        "By default, an AI agent interviews you about your project.",
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


def _add_plan_parser(subs) -> None:
    """Add the plan subcommand to the parser.

    Args:
        subs: Subparsers action from the parent parser.
    """
    p = subs.add_parser(
        "plan",
        help="Generate a structured plan.md for test-suite generation",
        description="Analyze an objective and its constraints, then call an agent "
        "to write a detailed generation plan that guides test-suite creation.",
    )
    p.add_argument(_OBJECTIVE_POS, help="Path to objective YAML")
    p.add_argument(
        _PROFILES_FLAG,
        default=DEFAULT_PROFILES_PATH,
        help=_PROFILES_HELP,
    )
    p.add_argument(
        _WORKSPACE_FLAG,
        default=None,
        help="Workspace directory (default: objective file's parent)",
    )
    p.add_argument(
        "--force",
        action=_STORE_TRUE,
        help="Regenerate plan.md even if it already exists",
    )


def _add_fit_parser(subs) -> None:
    """Add the fit subcommand to the parser.

    Args:
        subs: Subparsers action from the parent parser.
    """
    p = subs.add_parser(
        "fit",
        help="Generate and harden test suites for an objective",
        description="Generate pytest train suites, validate against constraints, "
        "run adversarial review, and save progress to a checkpoint. "
        "Use --task to process specific tasks (e.g. --task foo --task bar).",
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
        "-y",
        "--auto",
        action=_STORE_TRUE,
        help="Auto-accept tests and adversarial review (no interactive prompts)",
    )
    p.add_argument(
        "--auto-tests",
        action=_STORE_TRUE,
        help="Auto-approve generated train suites (skip the approve/edit/reject prompt)",
    )
    p.add_argument(
        "--auto-adversary",
        action=_STORE_TRUE,
        help="Auto-accept adversarial report (skip the improve/done prompt)",
    )
    p.add_argument(
        "--evaluate", action=_STORE_TRUE, help="Automatically run evaluation after fit completes"
    )
    p.add_argument(
        _WORKSPACE_FLAG,
        default=None,
        help="Workspace directory for artifacts (default: objective file's parent)",
    )
    p.add_argument(
        "--dry-run",
        action=_STORE_TRUE,
        help="Display generation prompts without calling agents",
    )
    p.add_argument(
        _TASK_FLAG,
        action="append",
        dest=_TASKS_ATTR,
        help="Process only named task(s); repeatable (e.g. --task foo --task bar)",
    )
    p.add_argument(
        "--demo",
        action=_STORE_TRUE,
        help="Simulate the fit workflow with canned data (no API key required)",
    )


def _add_evaluate_parser(subs) -> None:
    """Add the evaluate subcommand to the parser.

    Args:
        subs: Subparsers action from the parent parser.
    """
    p = subs.add_parser(
        "evaluate",
        help="Implement code from a checkpoint and verify against tests",
        description="Load a checkpoint, send a curriculum to the implementation agent, "
        "and verify the result against train suites and hidden holdout evals.",
    )
    p.add_argument(_OBJECTIVE_POS, nargs="?", default=None, help=_OBJECTIVE_POS_HELP)
    p.add_argument(
        _OBJECTIVE_FLAG,
        default=None,
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
        "--no-sandbox", action=_STORE_TRUE, help="Run pytest on host instead of Docker sandbox"
    )
    p.add_argument(
        _WORKSPACE_FLAG,
        default=None,
        help="Workspace directory for artifacts (default: objective file's parent)",
    )


def _add_checkpoint_parser(subs) -> None:
    """Add the checkpoint subcommand to the parser.

    Args:
        subs: Subparsers action from the parent parser.
    """
    p = subs.add_parser(
        "checkpoint",
        help="Show checkpoint progress and optimizer status",
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
        help="Print machine-readable checkpoint status JSON",
    )
    p.add_argument(_WORKSPACE_FLAG, default=None, help=_WORKSPACE_HELP)


def _add_show_parser(subs) -> None:
    """Add the show subcommand to the parser.

    Args:
        subs: Subparsers action from the parent parser.
    """
    p = subs.add_parser(
        "show",
        help="Show generated test suite and adversarial report for a task",
        description="Display the train suite source and adversarial report for a "
        "specific task from the checkpoint. Shortcut for `crucis checkpoint --task`.",
    )
    p.add_argument("task_name", help="Task name to inspect")
    p.add_argument(_CHECKPOINT_FLAG, default=DEFAULT_CHECKPOINT_PATH, help=_CHECKPOINT_HELP)
    p.add_argument(_JSON_OPTION, action=_STORE_TRUE, help=_JSON_HELP)
    p.add_argument(_WORKSPACE_FLAG, default=None, help=_WORKSPACE_HELP)


def _add_add_task_parser(subs) -> None:
    """Add the add-task subcommand to the parser.

    Args:
        subs: Subparsers action from the parent parser.
    """
    p = subs.add_parser(
        "add-task",
        help="Add a task to an objective file",
        description="Append a new task entry to an existing objective YAML file.",
    )
    p.add_argument(_OBJECTIVE_POS, help=_OBJECTIVE_POS_HELP)
    p.add_argument("--name", required=True, help="Task name (must be a valid Python identifier)")
    p.add_argument("--description", default=None, help="Task description")
    p.add_argument("--signature", default=None, help="Function signature hint")


def _add_add_eval_parser(subs) -> None:
    """Add the add-eval subcommand to the parser.

    Args:
        subs: Subparsers action from the parent parser.
    """
    p = subs.add_parser(
        "add-eval",
        help="Add a train eval to an objective file",
        description="Append a train_evals entry to an objective file, "
        "either at the top level or to a specific task.",
    )
    p.add_argument(_OBJECTIVE_POS, help=_OBJECTIVE_POS_HELP)
    p.add_argument(_TASK_FLAG, default=None, help="Task name to add eval to (default: top-level)")
    p.add_argument("--input", required=True, dest="eval_input", help="Eval input expression")
    p.add_argument("--output", required=True, dest="eval_output", help="Expected output expression")


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


def _add_profiles_parser(subs) -> None:
    """Add the profiles subcommand to the parser.

    Args:
        subs: Subparsers action from the parent parser.
    """
    p = subs.add_parser(
        "profiles",
        help="List available constraint profiles",
        description="Load and display all named profiles from a constraint profiles YAML file.",
    )
    p.add_argument(
        _PROFILES_FLAG,
        default=DEFAULT_PROFILES_PATH,
        help=_PROFILES_HELP,
    )
    p.add_argument(_WORKSPACE_FLAG, default=".", help=_WORKSPACE_HELP)


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
    p.add_argument(_JSON_OPTION, action=_STORE_TRUE, help=_JSON_HELP)


def _add_optimizer_worker_parser(subs) -> None:
    """Add the optimizer-worker subcommand to the parser.

    Args:
        subs: Subparsers action from the parent parser.
    """
    p = subs.add_parser(
        "optimizer-worker",
        help="Run background optimizer worker in foreground",
        description="Run one queued optimizer drain pass by default, or continuous loop mode.",
    )
    p.add_argument(_WORKSPACE_FLAG, default=".", help=_WORKSPACE_HELP)
    p.add_argument(
        "--loop",
        action=_STORE_TRUE,
        help="Run continuously instead of one-shot processing",
    )
    p.add_argument(_JSON_OPTION, action=_STORE_TRUE, help=_JSON_HELP)


def _add_migrate_parser(subs) -> None:
    """Add the migrate subcommand to the parser.

    Args:
        subs: Subparsers action from the parent parser.
    """
    p = subs.add_parser(
        "migrate",
        help="Convert legacy objective/checkpoint files to current schema",
        description="Migrate old spec.yaml or .session.json files to the current "
        "objective.yaml and .checkpoint.json formats.",
    )
    p.add_argument("--objective-in", help="Legacy objective file to read")
    p.add_argument("--objective-out", help="New objective file to write")
    p.add_argument("--checkpoint-in", help="Legacy checkpoint file to read")
    p.add_argument("--checkpoint-out", help="New checkpoint file to write")


def _add_promote_parser(subs) -> None:
    """Add the promote subcommand to the parser.

    Args:
        subs: Subparsers action from the parent parser.
    """
    p = subs.add_parser(
        "promote",
        help="Promote an optimizer candidate policy to active",
        description="Replace the active optimizer policy with a winning candidate "
        "from a completed optimization run.",
    )
    p.add_argument("--run-id", required=True, help="Run ID of candidate to promote")
    p.add_argument(_WORKSPACE_FLAG, default=".", help=_WORKSPACE_HELP)
    p.add_argument(
        "--force",
        action=_STORE_TRUE,
        help="Promote even when candidate-ready metadata is missing or mismatched",
    )


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
    optimizer_status = load_optimizer_status(resolved.parent)
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
                    display_train_suite_source(progress.train_suite_source)
                if progress.adversarial_report:
                    display_adversarial_report(progress.adversarial_report)
                if not progress.train_suite_source and not progress.adversarial_report:
                    print(f"Task '{task_name}' has no generated data yet.")
            return

    display_error(f"Task '{task_name}' not found in checkpoint.")
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    """Parse CLI args and dispatch to fit/evaluate/checkpoint/migrate.

    Args:
        argv: Optional CLI arguments; defaults to process arguments when None.
    """
    raw_args = list(sys.argv[1:] if argv is None else argv)
    _fail_on_legacy_usage(raw_args)

    args = build_parser().parse_args(raw_args)
    handlers = {
        "init": run_init_command,
        "plan": run_plan_command,
        "fit": _handle_fit_command,
        "show": run_show_command,
        "add-task": run_add_task_command,
        "add-eval": run_add_eval_command,
        _EVALUATE_CMD: _handle_evaluate_command,
        "checkpoint": _handle_checkpoint_command,
        "validate": run_validate_command,
        "profiles": run_profiles_command,
        "doctor": run_doctor_command,
        "optimizer-worker": run_optimizer_worker_command,
        "migrate": run_migrate,
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
        display_error(f"No objective file specified. Usage: crucis {command} <objective.yaml>")
        raise SystemExit(2)
    objective_path = Path(raw_path)
    if check_exists and not objective_path.exists():
        display_error(f"Objective file not found: {objective_path}")
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
    print("[demo mode — no agents will be called]\n")

    progress_list = []
    for idx, task in enumerate(tasks, 1):
        display_task_header(task.name, index=idx, total=len(tasks))
        display_train_suite_source(_DEMO_TEST)
        display_hardening_cycle(task.name, 1, 1)
        display_adversarial_report(_DEMO_REPORT)
        progress_list.append(
            TaskProgress(name=task.name, status=TrainingStatus.complete)
        )

    state = CheckpointState(task_progress=progress_list)
    display_fit_complete(state, objective_path=str(objective_path))
    print("Demo complete — no agents were called. Remove --demo to run for real.")


def _handle_fit_command(args: argparse.Namespace) -> None:
    """Execute fit command preflight and dispatch.

    Args:
        args: Parsed CLI arguments object.
    """
    objective_path = _resolve_objective_path(args, "fit", check_exists=True)
    workspace = Path(args.workspace).resolve() if args.workspace else None
    effective_workspace = workspace or objective_path.parent
    _ensure_runtime_settings(effective_workspace)

    if bool(getattr(args, "demo", False)):
        _run_demo_fit(objective_path, Path(args.profiles), effective_workspace)
        return

    dry_run = bool(getattr(args, "dry_run", False))
    config = Config()
    if not dry_run:
        auto_evaluate = bool(getattr(args, "evaluate", False))
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
    else:
        auto_evaluate = False

    auto_all = bool(getattr(args, "auto", False))
    fit_kwargs: dict = dict(
        objective_path=objective_path,
        profiles_path=Path(args.profiles),
        checkpoint_path=Path(args.checkpoint),
        auto_tests=auto_all or bool(getattr(args, "auto_tests", False)),
        auto_adversary=auto_all or bool(getattr(args, "auto_adversary", False)),
        auto_evaluate=auto_evaluate,
        workspace=workspace,
    )
    if dry_run:
        fit_kwargs["dry_run"] = True
    task_names = getattr(args, _TASKS_ATTR, None)
    if task_names:
        fit_kwargs["task_names"] = task_names
    try:
        run_fit(**fit_kwargs)
    except (ValueError, RuntimeError) as exc:
        display_error(str(exc))
        raise SystemExit(1) from exc


def _handle_evaluate_command(args: argparse.Namespace) -> None:
    """Execute evaluate command preflight and dispatch.

    Args:
        args: Parsed CLI arguments object.
    """
    objective_path = _resolve_objective_path(args, _EVALUATE_CMD)
    eval_workspace = Path(args.workspace).resolve() if args.workspace else None
    effective_workspace = eval_workspace or objective_path.parent
    _ensure_runtime_settings(effective_workspace)
    use_sandbox = not bool(getattr(args, "no_sandbox", False))
    config = Config()
    _run_preflight_or_exit(
        workspace=effective_workspace,
        config=config,
        required_agents={config.implementation_agent},
        require_pytest=not use_sandbox or (use_sandbox and not check_docker_available()),
    )
    run_evaluate(
        objective_path=objective_path,
        profiles_path=Path(args.profiles),
        checkpoint_path=Path(args.checkpoint),
        use_sandbox=use_sandbox,
        workspace=eval_workspace,
    )


def _handle_checkpoint_command(args: argparse.Namespace) -> None:
    """Execute checkpoint display command.

    Args:
        args: Parsed CLI arguments object.
    """
    checkpoint_path = Path(args.checkpoint)
    workspace = getattr(args, "workspace", None)
    if workspace and not checkpoint_path.is_absolute():
        checkpoint_path = Path(workspace).resolve() / checkpoint_path
    task_name = getattr(args, "task", None)
    as_json = bool(getattr(args, _JSON_ATTR, False))
    if task_name:
        _show_task_detail(checkpoint_path, task_name, as_json=as_json)
    else:
        show_checkpoint(checkpoint_path, as_json=as_json)


def run_validate_command(args: argparse.Namespace) -> None:
    """Validate an objective file and optionally its profiles.

    Args:
        args: Parsed CLI arguments object.
    """
    objective_path = Path(args.objective_path)
    try:
        objective = parse_objective(objective_path)
    except ValueError as exc:
        display_error(str(exc))
        raise SystemExit(1) from exc

    print(f"Objective '{objective.name}' is valid.")
    print(f"  Tasks: {len(objective.tasks)}")
    for task in objective.tasks:
        print(f"    - {task.name}")

    profiles_path = getattr(args, _PROFILES_ATTR, None)
    if profiles_path:
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
        print(f"  Profiles file valid. Available: {_JOIN_SEP.join(available)}")


def run_profiles_command(args: argparse.Namespace) -> None:
    """List available constraint profiles from a profiles YAML file.

    Args:
        args: Parsed CLI arguments object.
    """
    workspace = Path(args.workspace).resolve()
    profiles_path = Path(args.profiles)
    if not profiles_path.is_absolute():
        profiles_path = workspace / profiles_path

    try:
        profiles = load_profiles(profiles_path)
    except ValueError as exc:
        display_error(str(exc))
        raise SystemExit(1) from exc

    profile_names = sorted(k for k in profiles if k != _TASKS_ATTR)
    if not profile_names:
        print("No profiles defined.")
        return

    print(f"Available profiles ({profiles_path}):")
    for name in profile_names:
        profile = profiles[name]
        primary_keys = sorted(profile.get("primary", {}).keys())
        summary = _JOIN_SEP.join(primary_keys[:_MAX_PROFILE_KEYS_SHOWN])
        if len(primary_keys) > _MAX_PROFILE_KEYS_SHOWN:
            summary += f", ... ({len(primary_keys)} total)"
        print(f"  {name}: {summary or '(empty)'}")


def run_show_command(args: argparse.Namespace) -> None:
    """Show test suite and adversarial report for a specific task.

    Args:
        args: Parsed CLI arguments object.
    """
    checkpoint_path = Path(args.checkpoint)
    workspace = getattr(args, "workspace", None)
    if workspace and not checkpoint_path.is_absolute():
        checkpoint_path = Path(workspace).resolve() / checkpoint_path
    task_name = args.task_name
    as_json = bool(getattr(args, _JSON_ATTR, False))
    _show_task_detail(checkpoint_path, task_name, as_json=as_json)


def _load_objective_yaml_mapping(objective_path: Path) -> dict:
    """Load objective YAML and require a top-level mapping."""
    import yaml

    try:
        raw_text = objective_path.read_text(encoding=_TEXT_ENCODING)
    except FileNotFoundError:
        display_error(f"Objective file not found: {objective_path}")
        raise SystemExit(1) from None
    except OSError as exc:
        display_error(f"Could not read objective file {objective_path}: {exc}")
        raise SystemExit(1) from exc

    try:
        payload = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        display_error(f"Could not parse YAML in {objective_path}: {exc}")
        raise SystemExit(1) from exc

    if not isinstance(payload, dict):
        display_error("Objective file is not a valid YAML mapping.")
        raise SystemExit(1)
    return payload


def _write_validated_objective_atomic(
    objective_path: Path,
    raw: dict,
    failure_prefix: str,
) -> None:
    """Write updated objective atomically after schema validation."""
    import yaml

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=_TEXT_ENCODING,
            dir=str(objective_path.parent),
            prefix=f".{objective_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(yaml.safe_dump(raw, sort_keys=False))
        try:
            parse_objective(temp_path)
        except ValueError as exc:
            display_error(f"{failure_prefix}: {exc}")
            raise SystemExit(1) from exc
        temp_path.replace(objective_path)
    except OSError as exc:
        display_error(f"Could not update objective file {objective_path}: {exc}")
        raise SystemExit(1) from exc
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def run_add_task_command(args: argparse.Namespace) -> None:
    """Add a task to an objective file.

    Args:
        args: Parsed CLI arguments object.
    """
    objective_path = Path(args.objective_path)
    raw = _load_objective_yaml_mapping(objective_path)

    task_entry: dict = {"name": args.name}
    if args.description:
        task_entry["description"] = args.description
    if args.signature:
        task_entry["signature"] = args.signature

    if _TASKS_ATTR not in raw:
        raw[_TASKS_ATTR] = []
    if not isinstance(raw[_TASKS_ATTR], list):
        display_error("Objective field `tasks` must be a list.")
        raise SystemExit(1)
    raw[_TASKS_ATTR].append(task_entry)

    _write_validated_objective_atomic(
        objective_path,
        raw,
        "Validation failed after adding task",
    )
    print(f"Added task '{args.name}' to {objective_path}")


def run_add_eval_command(args: argparse.Namespace) -> None:
    """Add a train eval entry to an objective file.

    Args:
        args: Parsed CLI arguments object.
    """
    objective_path = Path(args.objective_path)
    raw = _load_objective_yaml_mapping(objective_path)

    eval_entry = {"input": args.eval_input, "output": args.eval_output}
    task_name = getattr(args, "task", None)

    if task_name:
        tasks = raw.get(_TASKS_ATTR, [])
        if not isinstance(tasks, list):
            display_error("Objective field `tasks` must be a list.")
            raise SystemExit(1)
        target = next(
            (t for t in tasks if isinstance(t, dict) and t.get("name") == task_name),
            None,
        )
        if target is None:
            display_error(f"Task '{task_name}' not found in objective.")
            raise SystemExit(1)
        if _TRAIN_EVALS_KEY not in target:
            target[_TRAIN_EVALS_KEY] = []
        if not isinstance(target[_TRAIN_EVALS_KEY], list):
            display_error(f"Task '{task_name}' field `train_evals` must be a list.")
            raise SystemExit(1)
        target[_TRAIN_EVALS_KEY].append(eval_entry)
    else:
        if _TRAIN_EVALS_KEY not in raw:
            raw[_TRAIN_EVALS_KEY] = []
        if not isinstance(raw[_TRAIN_EVALS_KEY], list):
            display_error("Objective field `train_evals` must be a list.")
            raise SystemExit(1)
        raw[_TRAIN_EVALS_KEY].append(eval_entry)

    _write_validated_objective_atomic(
        objective_path,
        raw,
        "Validation failed after adding eval",
    )
    scope = f"task '{task_name}'" if task_name else "top-level"
    print(f"Added eval to {scope} in {objective_path}")


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
        display_error(f"Invalid objective '{objective_path}': {exc}")
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
    display_evaluation_result(passed)
    if not passed:
        raise SystemExit(1)


def run_migrate(args: argparse.Namespace) -> None:
    """Run objective/checkpoint migration operations.

    Args:
        args: Parsed CLI arguments object.
    """
    objective_pair = (args.objective_in, args.objective_out)
    checkpoint_pair = (args.checkpoint_in, args.checkpoint_out)

    if bool(objective_pair[0]) != bool(objective_pair[1]):
        display_error("Objective migration requires both --objective-in and --objective-out.")
        raise SystemExit(2)

    if bool(checkpoint_pair[0]) != bool(checkpoint_pair[1]):
        display_error("Checkpoint migration requires both --checkpoint-in and --checkpoint-out.")
        raise SystemExit(2)

    if not objective_pair[0] and not checkpoint_pair[0]:
        display_error(
            "Nothing to migrate. Provide objective and/or checkpoint input/output pairs."
        )
        raise SystemExit(2)

    if objective_pair[0]:
        try:
            migrate_objective_file(Path(objective_pair[0]), Path(objective_pair[1]))
        except (ValueError, OSError) as exc:
            display_error(str(exc))
            raise SystemExit(1) from exc
        print(f"Migrated objective: {objective_pair[0]} -> {objective_pair[1]}")
    if checkpoint_pair[0]:
        try:
            migrate_checkpoint_file(Path(checkpoint_pair[0]), Path(checkpoint_pair[1]))
        except (ValueError, OSError) as exc:
            display_error(str(exc))
            raise SystemExit(1) from exc
        print(f"Migrated checkpoint: {checkpoint_pair[0]} -> {checkpoint_pair[1]}")


def run_promote(args: argparse.Namespace) -> None:
    """Promote one optimizer candidate policy into active policy.

    Args:
        args: Parsed CLI arguments object.
    """
    workspace = Path(args.workspace).resolve()
    run_id = str(args.run_id)
    force = bool(getattr(args, "force", False))

    status = load_optimizer_status(workspace)
    if not force:
        if status is None:
            display_error(
                "No optimizer status found for this workspace. "
                "Run `crucis checkpoint` to discover candidate-ready runs or use "
                "`crucis promote --run-id <id> --force`."
            )
            raise SystemExit(1)
        if not status.candidate_ready or status.candidate_run_id != run_id:
            display_error(
                f"Run `{run_id}` is not marked candidate-ready for promotion. "
                "Use the candidate shown by `crucis checkpoint` or pass --force "
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


def _is_interactive_terminal() -> bool:
    """Return True when both stdin and stdout are attached to a TTY."""
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def run_init_command(args: argparse.Namespace) -> None:
    """Scaffold a new Crucis workspace with starter files.

    Args:
        args: Parsed CLI arguments object.
    """
    workspace = Path(args.workspace).resolve()
    no_agent = bool(getattr(args, "no_agent", False))
    require_agent = bool(getattr(args, "require_agent", False))

    if no_agent and require_agent:
        display_error("Cannot use --no-agent together with --require-agent.")
        raise SystemExit(2)

    if not no_agent:
        if _try_agent_onboarding(workspace, args):
            return
        if require_agent:
            display_error("Agent onboarding is required but did not complete.")
            raise SystemExit(1)

    name = str(getattr(args, "name", "my_project"))
    created = scaffold_workspace(workspace, name=name)
    if not created:
        print("Workspace already initialized (all files exist).")
        return
    for path in created:
        print(f"  Created: {path}")
    _print_next_steps(workspace)


def _try_agent_onboarding(workspace: Path, args: argparse.Namespace) -> bool:
    """Attempt agent-driven onboarding, returning True on success.

    Args:
        workspace: Target workspace directory.
        args: Parsed CLI arguments with optional --agent flag.

    Returns:
        True when the agent completed and generated valid files.
    """
    import shutil

    from crucis.config import Config
    from crucis.intake.scaffold import run_agent_onboarding, validate_onboarding_output

    config = Config()
    agent = getattr(args, "agent", None) or config.generation_agent
    model = config.generation_model
    require_agent = bool(getattr(args, "require_agent", False))

    if not _is_interactive_terminal():
        message = (
            "Agent onboarding requires an interactive terminal. "
            "Re-run in an interactive shell, or pass --no-agent to scaffold static templates."
        )
        if require_agent:
            display_error(message)
            raise SystemExit(1)
        print("Non-interactive terminal detected. Skipping agent onboarding and using static templates.")
        return False

    if shutil.which(agent) is None:
        message = f"Agent '{agent}' not found on PATH."
        if require_agent:
            display_error(
                f"{message} Install it, remove --require-agent, or pass --no-agent."
            )
            raise SystemExit(1)
        print(f"{message} Using static templates.")
        return False

    success = run_agent_onboarding(workspace, agent, model)
    if not success:
        message = "Agent onboarding did not complete."
        if require_agent:
            display_error(f"{message} Remove --require-agent or pass --no-agent.")
            raise SystemExit(1)
        print(f"{message} Using static templates.")
        return False

    if not validate_onboarding_output(workspace):
        message = "Agent output is incomplete or invalid."
        if require_agent:
            display_error(f"{message} Remove --require-agent or pass --no-agent.")
            raise SystemExit(1)
        print(f"{message} Using static templates.")
        return False

    _print_next_steps(workspace)
    return True


def _print_next_steps(workspace: Path) -> None:
    """Print post-init guidance.

    Args:
        workspace: Workspace root directory.
    """
    print(f"\nWorkspace ready at {workspace}")
    print("Next steps:")
    print("  crucis plan objective.yaml              # generate a structured plan")
    print("  crucis fit objective.yaml -y            # generate and harden test suites")
    print("  crucis fit objective.yaml --task <name> # process a single task")
    print("  crucis fit objective.yaml --dry-run     # preview generation prompts")


def run_plan_command(args: argparse.Namespace) -> None:
    """Generate a structured plan.md for test-suite generation.

    Args:
        args: Parsed CLI arguments object.
    """
    objective_path = Path(args.objective_path)
    if not objective_path.exists():
        display_error(f"Objective file not found: {objective_path}")
        raise SystemExit(1)

    workspace = Path(args.workspace).resolve() if args.workspace else objective_path.parent
    _ensure_runtime_settings(workspace)

    plan_path = workspace / "plan.md"
    if plan_path.exists() and not bool(getattr(args, "force", False)):
        display_error(f"Plan already exists at {plan_path}. Use --force to regenerate.")
        raise SystemExit(1)

    objective = parse_objective(objective_path)
    profiles = load_profiles(_resolve_plan_profiles(workspace, Path(args.profiles)))
    effective_tasks = objective.tasks or [objective]
    constraints_map = {
        task.name: resolve_constraints(objective, profiles, task.name) for task in effective_tasks
    }

    config = Config()
    model_label = config.generation_model or "default model"
    print(f"Generating plan with {config.generation_agent} ({model_label})...")
    try:
        plan_content = build_generation_plan(objective, constraints_map, config)
    except (RuntimeError, ValueError) as exc:
        display_error(str(exc))
        raise SystemExit(1) from exc
    created = write_plan_to_workspace(plan_content, workspace)
    print(f"  Created: {created}")
    print("\nRun `crucis fit objective.yaml -y` to use this plan during generation.")


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
        _print_doctor_report(report)
    if not report.ok:
        raise SystemExit(1)


def run_optimizer_worker_command(args: argparse.Namespace) -> None:
    """Run foreground optimizer worker for automation/integration use.

    Args:
        args: Parsed CLI arguments object.
    """
    workspace = Path(args.workspace).resolve()
    loop_mode = bool(getattr(args, "loop", False))
    exit_code = run_optimizer_worker(workspace, once=not loop_mode)
    if not bool(getattr(args, _JSON_ATTR, False)) and exit_code == 0 and not loop_mode:
        print("Optimizer worker: no pending jobs. Nothing to do.")
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


def _fail_on_legacy_usage(argv: list[str]) -> None:
    """Reject removed legacy commands/flags with actionable upgrade hints.

    Args:
        argv: Optional CLI arguments; defaults to process arguments when None.
    """
    if not argv:
        return

    command = argv[0]
    if command in _LEGACY_COMMANDS:
        replacement = _LEGACY_COMMANDS[command]
        display_error(
            f"Legacy command `{command}` was removed. Use `crucis {replacement}`. "
            "If you still have old schema/session files, migrate first with "
            "`crucis migrate --objective-in ... --objective-out ...` and "
            "`crucis migrate --checkpoint-in ... --checkpoint-out ...`."
        )
        raise SystemExit(2)

    for arg in argv:
        if arg in _LEGACY_FLAGS:
            replacement = _LEGACY_FLAGS[arg]
            display_error(
                f"Legacy flag `{arg}` was removed. Use `{replacement}`. "
                "If you still have old schema/session files, migrate first with "
                "`crucis migrate --objective-in ... --objective-out ...` and "
                "`crucis migrate --checkpoint-in ... --checkpoint-out ...`."
            )
            raise SystemExit(2)


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


def _print_doctor_report(report) -> None:
    """Print human-readable diagnostics report.

    Args:
        report: Doctor report payload.
    """
    print(f"Workspace: {report.workspace}")
    for check in report.checks:
        prefix = {
            "ok": "OK",
            "warn": "WARN",
            "fail": "FAIL",
        }.get(check.status, check.status.upper())
        line = f"[{prefix}] {check.id}: {check.message}"
        if check.hint:
            line += f" | hint: {check.hint}"
        print(line)
    print("Doctor status: PASS" if report.ok else "Doctor status: FAIL")


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
