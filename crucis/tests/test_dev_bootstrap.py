"""Tests for developer bootstrap runner."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from crucis.dev_bootstrap import merged_pythonpath, repo_root_from_file, run


def test_repo_root_from_file_returns_package_parent(tmp_path: Path) -> None:
    """repo_root_from_file should return the repository root directory."""
    module_path = tmp_path / "crucis" / "dev_bootstrap.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("", encoding="utf-8")

    assert repo_root_from_file(module_path) == tmp_path


def test_merged_pythonpath_prepends_repo_and_dedupes() -> None:
    """merged_pythonpath should prepend repo root and drop duplicates."""
    repo_root = Path("/repo")
    existing = os.pathsep.join(["/repo", "/workspace", "/repo"])

    merged = merged_pythonpath(repo_root, existing)

    assert merged == os.pathsep.join(["/repo", "/workspace"])


def test_run_bootstraps_pythonpath_and_invokes_crucis(monkeypatch, tmp_path: Path) -> None:
    """run should call `python -m crucis` with repo root injected into PYTHONPATH."""
    recorded: dict = {}

    def fake_call(command, env, cwd):
        recorded["command"] = command
        recorded["env"] = env
        recorded["cwd"] = cwd
        return 0

    monkeypatch.setattr("crucis.dev_bootstrap.repo_root_from_file", lambda _p: tmp_path)
    monkeypatch.setattr("crucis.dev_bootstrap.subprocess.call", fake_call)

    exit_code = run(
        argv=["doctor", "--workspace", "."],
        environ={"PYTHONPATH": "/existing", "PATH": "/usr/bin"},
        cwd=tmp_path,
    )

    assert exit_code == 0
    assert recorded["command"][:3] == [sys.executable, "-m", "crucis"]
    assert recorded["command"][3:] == ["doctor", "--workspace", "."]
    assert recorded["cwd"] == tmp_path
    assert recorded["env"]["PYTHONPATH"] == f"{tmp_path}{os.pathsep}/existing"
