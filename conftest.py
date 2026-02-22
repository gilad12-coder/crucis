from pathlib import Path

import pytest

_FIXTURE_MAX_CYCLOMATIC = 5
_FIXTURE_MAX_LINES = 30


@pytest.fixture
def minimal_spec():
    """Provide a minimal ParsedObjective for testing.

    Returns:
        ParsedObjective with name "add" and basic examples.
    """
    from crucis.models import ParsedObjective

    return ParsedObjective(
        name="add",
        description="Add two integers and return their sum",
        train_evals=[
            {"input": "(1, 2)", "output": "3"},
            {"input": "(0, 0)", "output": "0"},
            {"input": "(-1, 1)", "output": "0"},
        ],
        signature="(a: int, b: int) -> int",
        tests_constraint_profile="strict",
    )


@pytest.fixture
def minimal_constraints():
    """Provide minimal TaskConstraints for testing.

    Returns:
        TaskConstraints with basic primary and secondary constraints.
    """
    from crucis.models import ConstraintSet, TaskConstraints

    return TaskConstraints(
        primary=ConstraintSet(
            max_cyclomatic_complexity=_FIXTURE_MAX_CYCLOMATIC,
            max_lines_per_function=_FIXTURE_MAX_LINES,
        ),
        secondary=ConstraintSet(
            require_docstrings=True,
        ),
        target_files=["src/add.py"],
    )


@pytest.fixture
def orchestrator_constraints_path():
    """Provide the path to the orchestrator constraints YAML file.

    Returns:
        Path to constraints/crucis.yaml.
    """
    return Path(__file__).parent / "constraints" / "crucis.yaml"
