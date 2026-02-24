"""Tests for session audit logging helpers."""

import json

from crucis.models import CLIResult
from crucis.persistence.audit import log_agent_call, log_interactive_agent_call
from crucis.persistence.events import EventLogger


def _read_events(logger: EventLogger) -> list[dict]:
    """Flush and read all JSONL events from a logger's backing file.

    Args:
        logger: Active event logger to read from.

    Returns:
        List of parsed event dicts.
    """
    logger.close()
    lines = logger.path.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines]


def test_log_agent_call_writes_full_details(tmp_path):
    """All fields should appear in the persisted JSONL record.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    with EventLogger(tmp_path, "test") as logger:
        result = CLIResult(exit_code=0, stdout="ok", stderr="")
        log_agent_call(
            logger,
            prompt="do something",
            result=result,
            agent="claude",
            model="sonnet",
            budget=1.0,
            duration_sec=2.5678,
            call_site="test_site",
        )

    events = _read_events(logger)
    assert len(events) == 1
    rec = events[0]
    assert rec["event"] == "agent_call"
    details = rec["details"]
    assert details["prompt"] == "do something"
    assert details["stdout"] == "ok"
    assert details["stderr"] == ""
    assert details["exit_code"] == 0
    assert details["agent"] == "claude"
    assert details["model"] == "sonnet"
    assert details["budget"] == 1.0
    assert details["duration_sec"] == 2.568
    assert details["call_site"] == "test_site"


def test_log_agent_call_noop_when_logger_is_none():
    """Passing None as logger should not raise."""
    result = CLIResult(exit_code=0, stdout="ok", stderr="")
    log_agent_call(
        None,
        prompt="p",
        result=result,
        agent="claude",
        model="sonnet",
        budget=1.0,
        duration_sec=0.1,
        call_site="test",
    )


def test_log_agent_call_includes_task_and_attempt(tmp_path):
    """Task and attempt fields should propagate to the top-level record.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    with EventLogger(tmp_path, "test") as logger:
        result = CLIResult(exit_code=1, stdout="", stderr="err")
        log_agent_call(
            logger,
            prompt="p",
            result=result,
            agent="codex",
            model="o3",
            budget=2.0,
            duration_sec=1.0,
            call_site="gen",
            task="login",
            attempt=2,
            max_attempts=3,
        )

    events = _read_events(logger)
    rec = events[0]
    assert rec["task"] == "login"
    assert rec["attempt"] == 2
    assert rec["max_attempts"] == 3


def test_log_interactive_agent_call_writes_metadata(tmp_path):
    """Interactive call metadata should be persisted correctly.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    with EventLogger(tmp_path, "test") as logger:
        log_interactive_agent_call(
            logger,
            agent="claude",
            model="sonnet",
            exit_code=0,
            duration_sec=5.1234,
            call_site="scaffold",
        )

    events = _read_events(logger)
    assert len(events) == 1
    rec = events[0]
    assert rec["event"] == "interactive_agent_call"
    details = rec["details"]
    assert details["agent"] == "claude"
    assert details["model"] == "sonnet"
    assert details["exit_code"] == 0
    assert details["duration_sec"] == 5.123
    assert details["call_site"] == "scaffold"


def test_log_interactive_agent_call_noop_when_logger_is_none():
    """Passing None as logger should not raise."""
    log_interactive_agent_call(
        None,
        agent="claude",
        model="sonnet",
        exit_code=0,
        duration_sec=0.1,
        call_site="test",
    )
