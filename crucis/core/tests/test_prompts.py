"""Tests for prompt builders."""

from pathlib import Path

from crucis.core.prompts import (
    build_adversary_prompt,
    build_evaluation_prompt,
    build_generation_prompt,
    build_probe_prompt,
)
from crucis.models import ConstraintSet, ParsedObjective, TaskConstraints, TrainEval
from crucis.persistence.policy import OptimizerPolicy


def _objective() -> ParsedObjective:
    """objective.

    Returns:
        Result of `_objective`.
    """
    return ParsedObjective(
        name="add",
        description="Add two integers",
        signature="add(a: int, b: int) -> int",
        train_evals=[TrainEval(input="(1, 2)", output="3")],
        holdout_evals=[{"input": "(999, 1)", "output": "1000"}],
        target_files=["src/add.py"],
    )


def _constraints() -> TaskConstraints:
    """constraints.

    Returns:
        Computed text result for this operation.
    """
    return TaskConstraints(
        primary=ConstraintSet(max_cyclomatic_complexity=5),
        secondary=ConstraintSet(require_docstrings=True),
        target_files=["src/add.py"],
        guidance=["Prefer pure functions"],
    )


def test_generation_prompt_includes_train_evals_not_holdout_literals():
    """Generation prompt should contain examples and hide holdout values."""
    prompt = build_generation_prompt(_objective(), _constraints())
    assert "Examples" in prompt
    assert "(1, 2)" in prompt
    assert "(999, 1)" not in prompt


def test_generation_prompt_accepts_adversarial_feedback():
    """Adversarial feedback should be appended when provided."""
    prompt = build_generation_prompt(
        _objective(),
        _constraints(),
        adversarial_feedback="Probe succeeded on hardcoded outputs",
    )
    assert "ADVERSARY FEEDBACK" in prompt


def test_adversary_prompt_requests_expected_json_shape():
    """Adversary prompt should request attack/generalization/probe lists."""
    prompt = build_adversary_prompt("def test_add(): pass", _objective(), _constraints())
    assert "attack_vectors" in prompt
    assert "generalization_gaps" in prompt
    assert "suggested_probe_tests" in prompt


def test_probe_prompt_excludes_holdout_literals():
    """Probe prompt should not leak holdout eval values."""
    prompt = build_probe_prompt("def test_add(): pass", _objective())
    assert "(999, 1)" not in prompt


def test_evaluation_prompt_contains_curriculum_and_holdout_warning():
    """Evaluation prompt should include curriculum path and holdout warning."""
    prompt = build_evaluation_prompt(
        [Path("tests/test_add.py")],
        curriculum_path=Path("curriculum.md"),
    )
    assert "curriculum.md" in prompt
    assert "holdout checks" in prompt.lower()


def test_evaluation_prompt_empty_paths_message():
    """Empty test paths should return no-op message."""
    prompt = build_evaluation_prompt([])
    assert "No generated test suites" in prompt


def test_policy_injection_appears_in_prompt_sections():
    """Policy sections should appear in stage-specific prompt builders."""
    policy = OptimizerPolicy(
        repository_skill="Use minimal, reviewable edits.",
        generation_directives="Favor broad edge-case test coverage.",
        adversary_directives="Probe for hardcoded solutions.",
        evaluation_directives="Prefer true algorithmic implementations.",
    )

    generation_prompt = build_generation_prompt(_objective(), _constraints(), policy=policy)
    adversary_prompt = build_adversary_prompt(
        "def test_add(): pass",
        _objective(),
        _constraints(),
        policy=policy,
    )
    evaluation_prompt = build_evaluation_prompt(
        [Path("tests/test_add.py")],
        curriculum_path=Path("curriculum.md"),
        policy=policy,
    )

    assert "Repository skill guidance" in generation_prompt
    assert "Stage directives (generation)" in generation_prompt
    assert "Stage directives (adversary)" in adversary_prompt
    assert "Stage directives (evaluation)" in evaluation_prompt


def test_generation_prompt_includes_context_files_content():
    """Generation prompt should render context file contents when provided."""
    context = {"src/helpers.py": "def helper(): return 42\n"}
    prompt = build_generation_prompt(
        _objective(), _constraints(), context_files_content=context
    )
    assert "src/helpers.py" in prompt
    assert "def helper()" in prompt


def test_generation_prompt_omits_context_section_when_empty():
    """Generation prompt without context files should not include context section."""
    prompt = build_generation_prompt(_objective(), _constraints())
    assert "Code context" not in prompt
