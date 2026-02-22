"""Tests for structured event logging."""

import json
from pathlib import Path

from crucis.persistence.events import EventLogger, logs_dir


def test_logs_dir_resolves_workspace_scoped_path(tmp_path: Path) -> None:
    """logs_dir should point under `.crucis/logs` in the workspace.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    assert logs_dir(tmp_path) == tmp_path / ".crucis" / "logs"


def test_event_logger_writes_jsonl_records(tmp_path: Path) -> None:
    """EventLogger should persist line-delimited JSON records.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    logger = EventLogger(tmp_path, "evaluate")
    logger.emit(
        "attempt_started",
        attempt=1,
        max_attempts=3,
        details={"use_sandbox": False},
    )
    logger.emit("attempt_failed", success=False, message="verification failed")
    path = logger.path
    logger.close()

    assert path is not None
    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["phase"] == "evaluate"
    assert first["event"] == "attempt_started"
    assert first["attempt"] == 1
    assert first["max_attempts"] == 3
    assert first["details"]["use_sandbox"] is False


def test_event_logger_context_manager_closes_handle(tmp_path: Path) -> None:
    """Context manager usage should write and close without errors.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    with EventLogger(tmp_path, "fit") as logger:
        logger.emit("run_started")
        path = logger.path

    assert path is not None
    assert path.exists()
