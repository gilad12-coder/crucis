"""Python version compatibility shims."""

import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        """Backport of StrEnum for Python 3.10."""

        @staticmethod
        def _generate_next_value_(name, start, count, last_values):
            """Generate lowercase member value from name for auto().

            Args:
                name: Enum member name.
                start: Start value (unused).
                count: Number of existing members (unused).
                last_values: Previously generated values (unused).

            Returns:
                Lowercased member name.
            """
            return name.lower()
