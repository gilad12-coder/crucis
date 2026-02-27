"""Cross-cutting constants shared across multiple Crucis subsystems.

Subsystem-specific constants live in each package's ``constants.py``.
Tuning parameters (model names, budgets, iteration counts) live in
``crucis.config.Config`` (env-var driven) and
``crucis.persistence.settings.OptimizerRuntimeSettings`` (YAML driven).
"""

import os


# Output / excerpt limits (characters)

LOG_EXCERPT_MAX_CHARS = 400
"""Max characters for feedback excerpts in event log entries."""


# Display

SEPARATOR_WIDTH = 40
"""Width of horizontal separator lines in terminal output."""


# Default paths

DEFAULT_CHECKPOINT_PATH = ".checkpoint.json"
"""Default checkpoint file name."""

DEFAULT_PROFILES_PATH = "constraints/profiles.yaml"
"""Default constraint profiles file path."""


# Miscellaneous

TEXT_ENCODING = "utf-8"
"""Standard text encoding for all file I/O operations."""


# Environment helpers

_SENSITIVE_PREFIXES = (
    "ANTHROPIC_",
    "OPENAI_",
    "AWS_SECRET",
    "GITHUB_TOKEN",
)
"""Env-var prefixes stripped by ``sanitized_env``."""


def sanitized_env() -> dict[str, str]:
    """Return a copy of ``os.environ`` with sensitive variables removed.

    Strips variables that could leak credentials or interfere with
    subprocess behavior (API keys, tokens, etc.).

    Returns:
        Sanitized copy of the current process environment.
    """
    env = dict(os.environ)
    for key in list(env):
        if any(key.startswith(prefix) for prefix in _SENSITIVE_PREFIXES):
            del env[key]
    return env


def bounded_excerpt(text: str, max_chars: int) -> str:
    """Return at most *max_chars* characters from *text*.

    Args:
        text: Source text to excerpt.
        max_chars: Maximum characters to keep.

    Returns:
        Truncated text, or original if within limits.
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."
