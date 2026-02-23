"""Rich terminal display helpers for Crucis output."""

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from crucis.defaults import SEPARATOR_WIDTH
from crucis.models import AdversarialReport, CheckpointState, TrainingStatus
from crucis.persistence.policy import OptimizerStatus

_YES = "yes"
_NO = "no"
_MAX_NAMES_SHOWN = 3

_console = Console()


def display_train_suite_source(source: str, console: Console | None = None) -> None:
    """Print train-suite source with Python syntax highlighting.

    Args:
        source: Python source code to validate or render.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    syntax = Syntax(source, "python", line_numbers=False)
    c.print(Panel(syntax, title="Generated Train Suite", border_style="cyan"))


def display_adversarial_report(
    report: AdversarialReport,
    console: Console | None = None,
) -> None:
    """Print adversarial findings with color-coded sections.

    Args:
        report: Adversarial report payload for the current task.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    sections = [
        ("Attack vectors", "red", report.attack_vectors),
        ("Generalization gaps", "yellow", report.generalization_gaps),
        ("Suggested probe tests", "green", report.suggested_probe_tests),
    ]
    c.print("[bold]Adversarial Report[/bold]")
    for title, color, items in sections:
        c.print(f"\n[bold]{title}[/bold]")
        if not items:
            c.print(f"[{color}]- (none)[/{color}]")
            continue
        for item in items:
            c.print(f"[{color}]- {item}[/{color}]")

    if report.probe_succeeded:
        c.print(
            "\n[bold red]Warning:[/bold red] adversarial probe succeeded; " "train suite is weak."
        )

    if report.probe_code:
        syntax = Syntax(report.probe_code, "python", line_numbers=False, word_wrap=True)
        c.print(Panel(syntax, title="Probe Implementation", border_style="magenta"))


def display_checkpoint_table(
    state: CheckpointState,
    optimizer_status: OptimizerStatus | None = None,
    console: Console | None = None,
) -> None:
    """Print a table summarizing per-task checkpoint progress.

    Args:
        state: Checkpoint state being processed.
        optimizer_status: Value for `optimizer_status` used by `display_checkpoint_table`.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    table = Table(title="Checkpoint Status")
    table.add_column("Task")
    table.add_column("Status")
    table.add_column("Train Suite")
    table.add_column("Adversarial")

    for progress in state.task_progress:
        suite_value = _YES if progress.train_suite_source else _NO
        adversarial_value = _YES if progress.adversarial_report else _NO
        table.add_row(progress.name, progress.status.value, suite_value, adversarial_value)
    c.print(table)
    _print_checkpoint_next_steps(c, state)

    if optimizer_status is not None:
        _print_optimizer_status(c, optimizer_status)


def _print_optimizer_status(c: Console, status: OptimizerStatus) -> None:
    """Print optimizer status details.

    Args:
        c: Rich console instance.
        status: Optimizer status to display.
    """
    c.print("\n[bold]Background Optimizer[/bold]")
    c.print(f"- state: {status.state}")
    if status.last_run_id:
        c.print(f"- last run: {status.last_run_id}")
    if status.last_trigger:
        c.print(f"- trigger: {status.last_trigger}")
    if status.promoted is not None:
        c.print(f"- promoted: {_YES if status.promoted else _NO}")
    if status.message:
        c.print(f"- message: {status.message}")
    if status.candidate_ready and status.candidate_run_id:
        c.print(f"- candidate ready: yes ({status.candidate_run_id})")
        c.print(f"- promote hint: crucis promote --run-id {status.candidate_run_id}")
    if str(status.state) == "failed":
        c.print("[dim](optimizer is optional and does not affect fit/evaluate)[/dim]")


def _print_checkpoint_next_steps(c: Console, state: CheckpointState) -> None:
    """Print contextual next-step hints based on checkpoint state.

    Args:
        c: Rich console instance.
        state: Checkpoint state being processed.
    """
    complete = sum(1 for p in state.task_progress if p.status == TrainingStatus.complete)
    total = len(state.task_progress)
    pending = sum(1 for p in state.task_progress if p.status == TrainingStatus.pending)
    c.print(f"[dim]{complete}/{total} tasks complete.[/dim]")
    if complete == total and total > 0:
        c.print("[dim]Next: crucis evaluate <objective.yaml>[/dim]")
    elif pending == total:
        c.print("[dim]Next: crucis fit <objective.yaml> -y[/dim]")
    else:
        incomplete = [p.name for p in state.task_progress if p.status != TrainingStatus.complete]
        names = ", ".join(incomplete[:_MAX_NAMES_SHOWN])
        if len(incomplete) > _MAX_NAMES_SHOWN:
            names += f" (+{len(incomplete) - _MAX_NAMES_SHOWN} more)"
        c.print(f"[dim]Remaining: {names}. Run `crucis fit` to continue.[/dim]")


def display_task_header(
    task_name: str,
    console: Console | None = None,
    index: int | None = None,
    total: int | None = None,
) -> None:
    """Print a header indicating which task is being processed.

    Args:
        task_name: Task name within the objective.
        console: Rich console instance used for output rendering.
        index: Value for `index` used by `display_task_header`.
        total: Value for `total` used by `display_task_header`.
    """
    c = console or _console
    progress = f" ({index}/{total})" if index is not None and total is not None else ""
    c.print(f"\n[bold cyan]{'─' * SEPARATOR_WIDTH}[/bold cyan]")
    c.print(f"[bold cyan]Training Task: {task_name}{progress}[/bold cyan]")
    c.print(f"[bold cyan]{'─' * SEPARATOR_WIDTH}[/bold cyan]\n")


def display_fit_complete(
    state: CheckpointState,
    console: Console | None = None,
    objective_path: str | None = None,
) -> None:
    """Print a summary indicating fit phase completion.

    Args:
        state: Checkpoint state being processed.
        console: Rich console instance used for output rendering.
        objective_path: Path to the objective file for next-step hint.
    """
    c = console or _console
    complete = sum(1 for p in state.task_progress if p.status == TrainingStatus.complete)
    total = len(state.task_progress)
    c.print(f"\n[bold green]{'─' * SEPARATOR_WIDTH}[/bold green]")
    c.print(f"[bold green]Fit complete: {complete}/{total} tasks complete[/bold green]")
    c.print(f"[bold green]{'─' * SEPARATOR_WIDTH}[/bold green]")
    obj_hint = f" --objective {objective_path}" if objective_path else ""
    c.print(f"[dim]Next: run `crucis evaluate{obj_hint}` to implement[/dim]")
    if total > 1 and complete < total:
        c.print("[dim]Tip: use --task <name> to re-run specific tasks[/dim]")
    c.print()


def display_dry_run_prompt(
    task_name: str,
    prompt: str,
    console: Console | None = None,
) -> None:
    """Print a generation prompt for dry-run preview.

    Args:
        task_name: Task name within the objective.
        prompt: Full generation prompt text.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    c.print(Panel(prompt, title=f"Generation Prompt: {task_name}", border_style="yellow"))


def display_error(message: str, console: Console | None = None) -> None:
    """Print an error message in red.

    Args:
        message: Message text to render in the console.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    c.print(f"[red]Error: {message}[/red]")


def display_spinner_context(message: str):
    """Return a spinner context manager for status output.

    Args:
        message: Message text to render in the console.

    Returns:
        Result of `display_spinner_context`.
    """
    return _console.status(message)


def display_hardening_cycle(
    task_name: str,
    cycle: int,
    max_cycles: int,
    console: Console | None = None,
) -> None:
    """Print the current adversarial hardening cycle number.

    Args:
        task_name: Task name within the objective.
        cycle: Current hardening cycle number (1-based).
        max_cycles: Maximum number of hardening cycles.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    c.print(f"[bold magenta]Hardening cycle {cycle}/{max_cycles} for {task_name}[/bold magenta]")


def display_evaluation_attempt(
    attempt: int,
    max_attempts: int,
    console: Console | None = None,
) -> None:
    """Print the current evaluation attempt number.

    Args:
        attempt: Current retry attempt number (1-based).
        max_attempts: Maximum number of retry attempts.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    c.print(f"\n[bold yellow]Evaluation attempt {attempt}/{max_attempts}...[/bold yellow]")


def display_evaluation_result(
    passed: bool,
    console: Console | None = None,
) -> None:
    """Print final evaluation result.

    Args:
        passed: Whether evaluation passed.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    if passed:
        c.print("\n[bold green]All tests passed.[/bold green]")
        c.print("[dim]Run `crucis checkpoint` to review progress.[/dim]")
    else:
        c.print("\n[bold red]Evaluation failed: tests did not pass.[/bold red]")
        c.print("[dim]Check errors above and re-run evaluation.[/dim]")


_MAX_FAILURE_OUTPUT_LINES = 30


def display_test_failure_output(
    output: str,
    console: Console | None = None,
) -> None:
    """Print bounded pytest failure output for user debugging.

    Args:
        output: Raw pytest output text.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    if not output.strip():
        return
    lines = output.strip().splitlines()
    if len(lines) > _MAX_FAILURE_OUTPUT_LINES:
        shown = lines[-_MAX_FAILURE_OUTPUT_LINES:]
        header = f"Test output (last {_MAX_FAILURE_OUTPUT_LINES} of {len(lines)} lines)"
    else:
        shown = lines
        header = "Test output"
    c.print(Panel("\n".join(shown), title=header, border_style="red"))


def display_workspace(workspace: Path, console: Console | None = None) -> None:
    """Print workspace path at fit start.

    Args:
        workspace: Workspace root directory.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    c.print(f"[bold]Workspace: {workspace}[/bold]")


def display_sandbox_status(
    available: bool,
    console: Console | None = None,
) -> None:
    """Print sandbox (Docker) availability status.

    Args:
        available: Whether Docker sandbox is available.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    if available:
        c.print("[green]Sandbox is available for isolated testing.[/green]")
    else:
        c.print("[red]Sandbox unavailable; tests will run on host.[/red]")
