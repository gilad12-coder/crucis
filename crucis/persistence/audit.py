"""Session audit logging for agent subprocess calls.

Persists full prompt, response, agent config, and timing for every
``run_cli_agent`` invocation via the existing :class:`EventLogger` JSONL
infrastructure.
"""

from __future__ import annotations

from crucis.models import CLIResult
from crucis.persistence.events import EventLogger

_DURATION_DECIMALS = 3
_EVENT_AGENT_CALL = "agent_call"
_EVENT_INTERACTIVE_CALL = "interactive_agent_call"


def log_agent_call(
    logger: EventLogger | None,
    *,
    prompt: str,
    result: CLIResult,
    agent: str,
    model: str,
    budget: float,
    duration_sec: float,
    call_site: str,
    task: str | None = None,
    attempt: int | None = None,
    max_attempts: int | None = None,
) -> None:
    """Persist a full agent call record to the session event log.

    Args:
        logger: Active event logger; no-op when *None*.
        prompt: Full prompt text sent to the agent.
        result: Complete CLIResult from the agent subprocess.
        agent: Agent name (claude or codex).
        model: Model name used for the call.
        budget: Budget value passed to the agent.
        duration_sec: Wall-clock duration of the agent call in seconds.
        call_site: Identifier for the originating function.
        task: Optional task name for context.
        attempt: Optional attempt number (1-based).
        max_attempts: Optional maximum attempts.
    """
    if logger is None:
        return
    logger.emit(
        _EVENT_AGENT_CALL,
        task=task,
        attempt=attempt,
        max_attempts=max_attempts,
        details={
            "call_site": call_site,
            "agent": agent,
            "model": model,
            "budget": budget,
            "duration_sec": round(duration_sec, _DURATION_DECIMALS),
            "prompt": prompt,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
    )


def log_interactive_agent_call(
    logger: EventLogger | None,
    *,
    agent: str,
    model: str,
    exit_code: int,
    duration_sec: float,
    call_site: str,
) -> None:
    """Persist metadata for an interactive (terminal-passthrough) agent session.

    Args:
        logger: Active event logger; no-op when *None*.
        agent: Agent name (claude or codex).
        model: Model name used for the call.
        exit_code: Process exit code from the interactive session.
        duration_sec: Wall-clock duration of the session in seconds.
        call_site: Identifier for the originating function.
    """
    if logger is None:
        return
    logger.emit(
        _EVENT_INTERACTIVE_CALL,
        details={
            "call_site": call_site,
            "agent": agent,
            "model": model,
            "exit_code": exit_code,
            "duration_sec": round(duration_sec, _DURATION_DECIMALS),
        },
    )
