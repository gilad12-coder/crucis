"""Constants shared across the intake subsystem (objective parsing and validation)."""

TRAIN_EVALS_KEY = "train_evals"
"""Internal dictionary key for training evaluation entries."""

HOLDOUT_EVALS_KEY = "holdout_evals"
"""Internal dictionary key for holdout evaluation entries."""

# User-facing aliases accepted in objective YAML files.
EXAMPLES_KEY = "examples"
"""User-facing alias for train_evals in objective YAML."""

HOLDOUT_KEY = "holdout"
"""User-facing alias for holdout_evals in objective YAML."""

NAME_KEY = "name"
"""Dictionary key for name fields in objectives and tasks."""

