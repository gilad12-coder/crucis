"""Developer bootstrap runner for source-tree Crucis usage.

This launcher enables running Crucis from any working directory without requiring
editable install or manual PYTHONPATH export.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path


def repo_root_from_file(module_file: Path) -> Path:
    """Resolve repository root from this module path.

    Args:
        module_file: Absolute or relative path to a Python module inside the repo.

    Returns:
        Path to the repository root directory.
    """
    return module_file.resolve().parents[1]


def merged_pythonpath(repo_root: Path, existing_pythonpath: str | None) -> str:
    """Prepend repo_root to PYTHONPATH while preserving existing entries.

    Args:
        repo_root: Repository root directory to prepend.
        existing_pythonpath: Current PYTHONPATH value, or None.

    Returns:
        Merged PYTHONPATH string with duplicates removed.
    """
    entries: list[str] = [str(repo_root)]
    if existing_pythonpath:
        entries.extend(part for part in existing_pythonpath.split(os.pathsep) if part)

    deduped: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if entry in seen:
            continue
        seen.add(entry)
        deduped.append(entry)
    return os.pathsep.join(deduped)


def run(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> int:
    """Run Crucis module with bootstrapped PYTHONPATH.

    Args:
        argv: Command-line arguments to forward. Defaults to sys.argv[1:].
        environ: Environment mapping override. Defaults to os.environ.
        cwd: Working directory for the subprocess.

    Returns:
        Subprocess exit code.
    """
    repo_root = repo_root_from_file(Path(__file__))
    env = dict(os.environ if environ is None else environ)
    env["PYTHONPATH"] = merged_pythonpath(repo_root, env.get("PYTHONPATH"))

    args = list(sys.argv[1:] if argv is None else argv)
    command = [sys.executable, "-m", "crucis", *args]
    return subprocess.call(command, env=env, cwd=cwd)


def main() -> None:
    """CLI entrypoint."""
    raise SystemExit(run())


if __name__ == "__main__":
    main()
