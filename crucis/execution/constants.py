"""Constants for the execution subsystem (sandbox and optimizer)."""

DOCKER_CHECK_TIMEOUT_SEC = 10
"""Timeout for ``docker info`` availability check."""

DOCKER_PYTEST_TIMEOUT_SEC = 120
"""Timeout for running pytest inside a Docker container."""

LOCK_STALE_MAX_AGE_SEC = 6 * 60 * 60
"""Worker lock is considered stale after this many seconds (6 hours)."""

EXCERPT_MAX_CHARS = 1200
"""Max characters for stdout/stderr excerpts in optimizer reports."""

DISABLE_OPTIMIZER_ENV = "CRUCIS_DISABLE_BACKGROUND_OPTIMIZER"
"""Env var that disables the background optimizer when set."""

MS_PER_SEC = 1000
"""Milliseconds per second, used for timestamp generation."""

PYTHONPATH_ENV = "PYTHONPATH"
"""Environment variable for Python module search path."""
