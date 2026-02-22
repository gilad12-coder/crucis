"""Cross-cutting constants shared across multiple Crucis subsystems.

Subsystem-specific constants live in each package's ``constants.py``.
Tuning parameters (model names, budgets, iteration counts) live in
``crucis.config.Config`` (env-var driven) and
``crucis.persistence.settings.OptimizerRuntimeSettings`` (YAML driven).
"""

# ---------------------------------------------------------------------------
# Output / excerpt limits (characters)
# ---------------------------------------------------------------------------

LOG_EXCERPT_MAX_CHARS = 400
"""Max characters for feedback excerpts in event log entries."""

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

SEPARATOR_WIDTH = 40
"""Width of horizontal separator lines in terminal output."""

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

DEFAULT_CHECKPOINT_PATH = ".checkpoint.json"
"""Default checkpoint file name."""

DEFAULT_PROFILES_PATH = "constraints/profiles.yaml"
"""Default constraint profiles file path."""

# ---------------------------------------------------------------------------
# Miscellaneous
# ---------------------------------------------------------------------------

TEXT_ENCODING = "utf-8"
"""Standard text encoding for all file I/O operations."""
