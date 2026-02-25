"""Rich terminal display helpers for Crucis output."""

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from crucis.defaults import SEPARATOR_WIDTH
from crucis.models import AdversarialReport, CheckpointState, TrainingStatus
from crucis.persistence.policy import OptimizerStatus

_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600

_YES = "yes"
_NO = "no"
_MAX_NAMES_SHOWN = 3
_COLOR_RED = "red"
_COLOR_YELLOW = "yellow"
_EXPLANATION_MAX_WIDTH = 50

_TRAINING_STATUS_STYLES: dict[str, tuple[str, str]] = {
    "pending": ("Pending", "yellow"),
    "train_suite_generated": ("Generated", "cyan"),
    "train_suite_approved": ("Approved", "cyan"),
    "adversarially_reviewed": ("Reviewed", "cyan"),
    "complete": ("Complete", "green"),
}

_console = Console(stderr=True)


def configure_console(
    no_color: bool = False,
    force_color: bool = False,
) -> None:
    """Reinitialize the module-level console with explicit color settings.

    Args:
        no_color: When True, strip all color/style markup from output.
        force_color: When True, emit ANSI color even when not a TTY.
    """
    global _console  # noqa: PLW0603
    if no_color:
        _console = Console(no_color=True, stderr=True)
    elif force_color:
        _console = Console(force_terminal=True, stderr=True)


def format_elapsed(seconds: float) -> str:
    """Format a duration in seconds into a concise human-readable string.

    Args:
        seconds: Duration in seconds (must be non-negative).

    Returns:
        Formatted string like "5s", "2m 34s", or "1h 12m".

    Raises:
        ValueError: If seconds is negative.
    """
    if seconds < 0:
        raise ValueError(f"seconds must be non-negative, got {seconds}")
    total = int(seconds)
    if total < _SECONDS_PER_MINUTE:
        return f"{total}s"
    if total < _SECONDS_PER_HOUR:
        m, s = divmod(total, _SECONDS_PER_MINUTE)
        return f"{m}m {s}s" if s or seconds != total else f"{m}m"
    h, remainder = divmod(total, _SECONDS_PER_HOUR)
    m = remainder // _SECONDS_PER_MINUTE
    return f"{h}h {m}m" if remainder or seconds != total else f"{h}h"


def display_test_suite_source(source: str, console: Console | None = None) -> None:
    """Print test-suite source with Python syntax highlighting.

    Args:
        source: Python source code to validate or render.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    syntax = Syntax(source, "python", line_numbers=False)
    c.print(Panel(syntax, title="Generated Test Suite", border_style="cyan"))


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
        ("Correctness issues", _COLOR_RED, report.correctness_issues),
        ("Attack vectors", _COLOR_RED, report.attack_vectors),
        ("Generalization gaps", _COLOR_YELLOW, report.generalization_gaps),
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
            "\n[bold red]Warning:[/bold red] adversarial probe succeeded; " "test suite is weak."
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
    table.add_column("Test Suite")
    table.add_column("Adversarial")

    for progress in state.task_progress:
        suite_value = _YES if progress.train_suite_source else _NO
        adversarial_value = _YES if progress.adversarial_report else _NO
        label, color = _TRAINING_STATUS_STYLES.get(
            progress.status.value, (progress.status.value, "white"),
        )
        table.add_row(progress.name, f"[{color}]{label}[/{color}]", suite_value, adversarial_value)
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
    if state.evaluation_passed:
        c.print("[bold green]Evaluation passed.[/bold green]")
    elif complete == total and total > 0:
        c.print("[dim]All tasks trained. Proceeding to evaluation.[/dim]")
    elif pending == total:
        c.print("[dim]No tasks trained yet.[/dim]")
    else:
        incomplete = [p.name for p in state.task_progress if p.status != TrainingStatus.complete]
        names = ", ".join(incomplete[:_MAX_NAMES_SHOWN])
        if len(incomplete) > _MAX_NAMES_SHOWN:
            names += f" (+{len(incomplete) - _MAX_NAMES_SHOWN} more)"
        c.print(f"[dim]Remaining: {names}[/dim]")


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
    elapsed_sec: float | None = None,
) -> None:
    """Print a summary indicating fit phase completion.

    Args:
        state: Checkpoint state being processed.
        console: Rich console instance used for output rendering.
        elapsed_sec: Wall-clock seconds for the fit phase, shown when provided.
    """
    c = console or _console
    complete = sum(1 for p in state.task_progress if p.status == TrainingStatus.complete)
    total = len(state.task_progress)
    suffix = f" in {format_elapsed(elapsed_sec)}" if elapsed_sec is not None else ""
    c.print(f"\n[bold green]{'─' * SEPARATOR_WIDTH}[/bold green]")
    c.print(f"[bold green]Fit complete: {complete}/{total} tasks complete{suffix}[/bold green]")
    c.print(f"[bold green]{'─' * SEPARATOR_WIDTH}[/bold green]")
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
    c.print(Panel(prompt, title=f"Generation Prompt: {task_name}", border_style=_COLOR_YELLOW))


def display_error(
    message: str,
    console: Console | None = None,
    hint: str | None = None,
) -> None:
    """Print an error message in red with an optional hint.

    Args:
        message: Message text to render in the console.
        console: Rich console instance used for output rendering.
        hint: Actionable suggestion shown below the error when provided.
    """
    c = console or _console
    c.print(f"[red]Error: {message}[/red]")
    if hint:
        c.print(f"[dim]Hint: {hint}[/dim]")


def display_warning(message: str, console: Console | None = None) -> None:
    """Print a warning message in yellow.

    Args:
        message: Message text to render in the console.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    c.print(f"[yellow]Warning: {message}[/yellow]")


def display_info(message: str, console: Console | None = None) -> None:
    """Print an informational message in dim style.

    Args:
        message: Message text to render in the console.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    c.print(f"[dim]{message}[/dim]")


def display_success(message: str, console: Console | None = None) -> None:
    """Print a success confirmation in green.

    Args:
        message: Message text to render in the console.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    c.print(f"[green]{message}[/green]")


def display_spinner_context(message: str):
    """Return a spinner context manager for status output.

    Args:
        message: Message text to render in the console.

    Returns:
        Result of `display_spinner_context`.
    """
    return _console.status(message)


def prompt_input(message: str) -> str:
    """Display a styled prompt and read user input.

    Args:
        message: Prompt text with optional Rich markup.

    Returns:
        User's stripped input string.
    """
    return _console.input(message).strip()


def display_hardening_cycle(
    task_name: str,
    cycle: int,
    max_cycles: int,
    console: Console | None = None,
) -> None:
    """Print the current adversarial review cycle number.

    Args:
        task_name: Task name within the objective.
        cycle: Current review cycle number (1-based).
        max_cycles: Maximum number of review cycles.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    c.print(f"[bold magenta]Review cycle {cycle}/{max_cycles} for {task_name}[/bold magenta]")


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
    attempt: int | None = None,
    max_attempts: int | None = None,
    complete_tasks: int | None = None,
    total_tasks: int | None = None,
    elapsed_sec: float | None = None,
) -> None:
    """Print final evaluation result.

    Args:
        passed: Whether evaluation passed.
        console: Rich console instance used for output rendering.
        attempt: Attempt number that succeeded (1-based), when available.
        max_attempts: Maximum number of retry attempts, when available.
        complete_tasks: Number of completed tasks in the checkpoint.
        total_tasks: Total number of tasks in the checkpoint.
        elapsed_sec: Wall-clock seconds for the evaluation phase, shown when provided.
    """
    c = console or _console
    if passed:
        parts = ["All tests passed."]
        if attempt is not None and max_attempts is not None:
            parts.append(f"(attempt {attempt}/{max_attempts})")
        if elapsed_sec is not None:
            parts.append(f"in {format_elapsed(elapsed_sec)}")
        c.print(f"\n[bold green]{' '.join(parts)}[/bold green]")
        if complete_tasks is not None and total_tasks is not None:
            c.print(f"[bold green]Evaluation passed — {complete_tasks}/{total_tasks} tasks complete.[/bold green]")
        else:
            c.print("[bold green]Evaluation passed.[/bold green]")
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


def display_validation_report(
    issues: list[dict],
    summary: str | None = None,
    console: Console | None = None,
) -> None:
    """Print semantic validation results with color-coded severity.

    Args:
        issues: List of issue dicts from the LLM review.
        summary: One-line overall assessment from the reviewer.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    if not issues:
        c.print("[bold green]Semantic review: all eval cases look correct.[/bold green]")
        if summary:
            c.print(f"[dim]{summary}[/dim]")
        return

    table = Table(title="Semantic Review Issues")
    table.add_column("Severity", style="bold")
    table.add_column("Type")
    table.add_column("Task")
    table.add_column("Input")
    table.add_column("Expected")
    table.add_column("Explanation", max_width=_EXPLANATION_MAX_WIDTH)
    table.add_column("Suggestion", max_width=_EXPLANATION_MAX_WIDTH, style="cyan")

    for issue in issues:
        severity = str(issue.get("severity", "warning"))
        style = _COLOR_RED if severity == "error" else _COLOR_YELLOW
        table.add_row(
            f"[{style}]{severity}[/{style}]",
            str(issue.get("eval_type", "")),
            str(issue.get("task", "")),
            str(issue.get("input", "")),
            str(issue.get("expected", "")),
            str(issue.get("explanation", "")),
            str(issue.get("suggestion", "")),
        )

    c.print(table)
    if summary:
        c.print(f"\n[dim]{summary}[/dim]")


_STATUS_STYLE = {"ok": "green", "warn": _COLOR_YELLOW, "fail": _COLOR_RED}
_STATUS_PREFIX = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}


def display_doctor_report(
    report,
    verbose: bool = False,
    console: Console | None = None,
) -> None:
    """Print human-readable diagnostics report with styled status lines.

    Args:
        report: Doctor report payload with workspace, checks, and ok fields.
        verbose: When False, only show warnings and failures.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    c.print(f"[bold]Workspace: {report.workspace}[/bold]")
    for check in report.checks:
        if not verbose and check.status == "ok":
            continue
        style = _STATUS_STYLE.get(check.status, "white")
        prefix = _STATUS_PREFIX.get(check.status, check.status.upper())
        line = f"[{style}][{prefix}][/{style}] {check.id}: {check.message}"
        if check.hint:
            line += f" [dim]| hint: {check.hint}[/dim]"
        c.print(line)
    warn_count = sum(1 for ck in report.checks if ck.status == "warn")
    if report.ok and warn_count:
        c.print(f"[green]Doctor status: PASS[/green] [dim]({warn_count} warning(s))[/dim]")
    elif report.ok:
        c.print("[green]Doctor status: PASS[/green]")
    else:
        c.print(f"[{_COLOR_RED}]Doctor status: FAIL[/{_COLOR_RED}]")


def display_agent_boundary(label: str, console: Console | None = None) -> None:
    """Print a dim separator line to frame agent output sections.

    Args:
        label: Short label like 'agent output' or 'end agent output'.
        console: Rich console instance used for output rendering.
    """
    c = console or _console
    c.print(f"[dim]--- {label} ---[/dim]", highlight=False)
