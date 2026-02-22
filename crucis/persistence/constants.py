"""Constants for the persistence subsystem (checkpoint, policy, settings)."""

MAX_POLICY_FIELD_CHARS = 20_000
"""Max characters allowed in a single optimizer policy field."""

POLICY_OVERRIDE_ENV = "CRUCIS_POLICY_OVERRIDE_JSON"
"""Env var for injecting an optimizer policy override as JSON."""

CRUCIS_DIR_NAME = ".crucis"
"""Name of the hidden workspace directory for Crucis state."""
