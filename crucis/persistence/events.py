"""Structured JSONL event logging for long-running Crucis workflows."""

from __future__ import annotations

import contextlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from crucis.defaults import TEXT_ENCODING
from crucis.persistence.settings import crucis_dir


def logs_dir(workspace: Path) -> Path:
    """Return workspace-local logs directory path.

    Args:
        workspace: Workspace root directory.

    Returns:
        Path to `.crucis/logs` under the workspace.
    """
    return crucis_dir(workspace) / "logs"


class EventLogger:
    """Append-only JSONL logger with failure-safe writes."""

    def __init__(self, workspace: Path, phase: str):
        """Create an event logger instance.

        Args:
            workspace: Workspace root directory.
            phase: High-level phase name (fit/evaluate/optimizer_worker).
        """
        self.workspace = workspace
        self.phase = phase
        self.path: Path | None = None
        self._handle: TextIO | None = None
        self._open()

    def _open(self) -> None:
        """Open backing JSONL file if possible."""
        try:
            directory = logs_dir(self.workspace)
            directory.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            filename = f"{self.phase}_{timestamp}_{os.getpid()}.jsonl"
            self.path = directory / filename
            self._handle = self.path.open("a", encoding=TEXT_ENCODING)
        except OSError:
            self.path = None
            self._handle = None

    def emit(
        self,
        event: str,
        *,
        message: str | None = None,
        success: bool | None = None,
        attempt: int | None = None,
        max_attempts: int | None = None,
        task: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Write one event record.

        Args:
            event: Event key describing a state transition.
            message: Optional short human-readable message.
            success: Optional success flag.
            attempt: Optional retry attempt (1-based).
            max_attempts: Optional maximum retries.
            task: Optional task name context.
            details: Optional structured metadata.
        """
        if self._handle is None:
            return
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "phase": self.phase,
            "event": event,
            "message": message,
            "success": success,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "task": task,
            "details": details or {},
        }
        try:
            self._handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
            self._handle.flush()
        except OSError:
            return

    def close(self) -> None:
        """Close the backing file handle when open."""
        if self._handle is None:
            return
        with contextlib.suppress(OSError):
            self._handle.close()
        self._handle = None

    def __enter__(self) -> EventLogger:
        """Return context-managed logger.

        Returns:
            Current logger instance.
        """
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        """Close logger on context manager exit.

        Args:
            _exc_type: Unused exception class from context manager protocol.
            _exc: Unused exception value from context manager protocol.
            _tb: Unused traceback from context manager protocol.
        """
        self.close()
