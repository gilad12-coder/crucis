"""Custom Jinja2 filters for prompt templates."""

from pathlib import Path


def path_to_module(file_path: str) -> str:
    """Convert a file path to a dotted Python module string.

    Args:
        file_path: Relative Python source file path (e.g. ``src/add.py``).

    Returns:
        Dotted module path string (e.g. ``src.add``).
    """
    return Path(file_path).with_suffix("").as_posix().replace("/", ".")


def bool_label(value: bool) -> str:
    """Convert a boolean to a human-readable yes/no label.

    Args:
        value: Boolean value.

    Returns:
        ``"yes"`` or ``"no"``.
    """
    return "yes" if value else "no"


def readable_name(field_name: str) -> str:
    """Convert a snake_case field name to space-separated words.

    Args:
        field_name: Snake-case identifier.

    Returns:
        Human-readable name with spaces.
    """
    return field_name.replace("_", " ")
