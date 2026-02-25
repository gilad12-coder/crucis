"""Constraint field classification registry.

Defines which ConstraintSet fields are advisory (soft) vs required (hard).
Hard constraints block the pipeline; soft constraints are advisory warnings.
"""

SOFT_CONSTRAINT_FIELDS: frozenset[str] = frozenset({
    "require_docstrings",
    "no_print_statements",
    "no_debugger_statements",
    "no_global_state",
    "require_type_annotations",
    "no_nested_imports",
    "no_star_imports",
    "max_local_variables",
})
"""Fields classified as advisory. All other ConstraintSet fields are required."""
