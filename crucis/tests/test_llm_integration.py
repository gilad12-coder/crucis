"""Integration tests that call a real LLM via Claude CLI.

Run with: pytest tests/test_llm_integration.py -m llm -v
These are excluded from normal runs via: pytest -m 'not llm'
"""

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from crucis.cli.runner import run_cli_agent
from crucis.config import Config
from crucis.core.adversary import parse_adversarial_report
from crucis.core.loop import (
    process_task,
    run_fit,
    validate_train_suite_constraints,
    validate_train_suite_syntax,
)
from crucis.core.prompts import build_adversary_prompt, build_generation_prompt
from crucis.core.test_generator import extract_python_from_response
from crucis.models import (
    AdversarialReport,
    ConstraintSet,
    ParsedObjective,
    TaskConstraints,
    TrainingStatus,
)


def _skip_if_no_claude():
    """Skip test if claude CLI is not available."""
    if shutil.which("claude") is None:
        pytest.skip("claude CLI not found")


def _spec():
    """Create a simple ParsedObjective for integration testing.

    Returns:
        ParsedObjective for a factorial function.
    """
    return ParsedObjective(
        name="factorial",
        description="Compute the factorial of a non-negative integer.",
        train_evals=[
            {"input": "(0)", "output": "1"},
            {"input": "(5)", "output": "120"},
        ],
        signature="(n: int) -> int",
    )


def _constraints():
    """Create constraints for integration testing.

    Returns:
        TaskConstraints with docstring and complexity requirements.
    """
    return TaskConstraints(
        primary=ConstraintSet(max_cyclomatic_complexity=10),
        secondary=ConstraintSet(require_docstrings=True),
        target_files=[],
    )


def _config():
    """Create a Config for integration testing.

    Returns:
        Config with default settings.
    """
    return Config()


# --- Component tests (each calls the LLM once in isolation) ---


@pytest.mark.llm
@pytest.mark.timeout(120)
class TestLLMGeneration:
    """Test that the generation agent produces valid, constraint-compliant code."""

    def test_generate_returns_valid_python(self):
        """Test that LLM generation returns syntactically valid Python."""
        _skip_if_no_claude()
        spec = _spec()
        constraints = _constraints()
        config = _config()
        prompt = build_generation_prompt(spec, constraints)
        result = run_cli_agent(
            prompt,
            config.generation_agent,
            config.generation_model,
            config.max_budget_usd,
        )
        source = extract_python_from_response(result.stdout)
        assert source != "", "LLM returned no extractable Python"
        syntax_ok, errors = validate_train_suite_syntax(source)
        assert syntax_ok, f"Generated code has syntax errors: {errors}"

    def test_generate_passes_constraints(self):
        """Test that LLM generation satisfies configured constraints."""
        _skip_if_no_claude()
        spec = _spec()
        constraints = _constraints()
        config = _config()
        prompt = build_generation_prompt(spec, constraints)
        result = run_cli_agent(
            prompt,
            config.generation_agent,
            config.generation_model,
            config.max_budget_usd,
        )
        source = extract_python_from_response(result.stdout)
        assert source != ""
        passed, violations = validate_train_suite_constraints(source, constraints)
        # If first attempt fails, try with feedback (mirrors real loop)
        if not passed:
            prompt_retry = build_generation_prompt(
                spec, constraints, constraint_feedback=violations
            )
            result = run_cli_agent(
                prompt_retry,
                config.generation_agent,
                config.generation_model,
                config.max_budget_usd,
            )
            source = extract_python_from_response(result.stdout)
            passed, violations = validate_train_suite_constraints(source, constraints)
        assert passed, f"Generated code violates constraints:\n{violations}"


@pytest.mark.llm
@pytest.mark.timeout(120)
class TestLLMCritique:
    """Test that the critic agent returns parseable JSON with flat string lists."""

    def test_adversarial_report_parses_to_model(self):
        """Test that real critic output parses into AdversarialReport."""
        _skip_if_no_claude()
        spec = _spec()
        constraints = _constraints()
        config = _config()
        train_suite_source = (
            "from factorial import factorial\n\n\n"
            "class TestFactorial:\n"
            '    """Tests for factorial."""\n\n'
            "    def test_zero(self):\n"
            '        """Test factorial of zero."""\n'
            "        assert factorial(0) == 1\n\n"
            "    def test_five(self):\n"
            '        """Test factorial of five."""\n'
            "        assert factorial(5) == 120\n"
        )
        prompt = build_adversary_prompt(train_suite_source, spec, constraints)
        result = run_cli_agent(
            prompt,
            config.critic_agent,
            config.critic_model,
            config.max_budget_usd,
        )
        adversarial_report = parse_adversarial_report(result.stdout)
        assert isinstance(adversarial_report, AdversarialReport)
        assert isinstance(adversarial_report.attack_vectors, list)
        # Every item must be a string, not a dict
        for item in adversarial_report.attack_vectors:
            assert isinstance(item, str), f"Expected str, got {type(item)}: {item}"
        for item in adversarial_report.generalization_gaps:
            assert isinstance(item, str), f"Expected str, got {type(item)}: {item}"
        for item in adversarial_report.suggested_probe_tests:
            assert isinstance(item, str), f"Expected str, got {type(item)}: {item}"


# --- E2E test (full flow with real LLM, only mock user review) ---


@pytest.mark.llm
@pytest.mark.timeout(300)
class TestLLMProcessFunction:
    """Full process_task flow with real LLM calls."""

    @patch("crucis.core.loop.prompt_adversarial_review", return_value=True)
    @patch("crucis.core.loop.prompt_user_review")
    def test_full_flow(self, mock_review, _):
        """Test the full generate → validate → adversarial_report flow with real LLM.

        Args:
            mock_review: Mocked prompt_user_review to auto-approve.
            _: Mocked prompt_adversarial_review (auto-accept).
        """
        _skip_if_no_claude()
        mock_review.side_effect = lambda source, **kwargs: (True, source)
        spec = _spec()
        constraints = _constraints()
        config = _config()
        progress = process_task("factorial", spec, constraints, config)
        assert progress.status == TrainingStatus.complete
        assert progress.train_suite_source is not None
        assert len(progress.train_suite_source) > 0
        assert progress.adversarial_report is not None
        assert isinstance(progress.adversarial_report.attack_vectors, list)


# --- Full run_fit E2E (spec YAML → completed session) ---


_E2E_SPEC = {
    "name": "math_utils",
    "description": "Simple math utility functions.",
    "tests_constraint_profile": "default",
    "target_files": ["math_utils.py"],
    "tasks": [
        {
            "name": "factorial",
            "description": (
                "Compute the factorial of a non-negative integer. "
                "factorial(0) returns 1. Raises ValueError for negative input."
            ),
            "signature": "(n: int) -> int",
            "train_evals": [
                {"input": "(0)", "output": "1"},
                {"input": "(5)", "output": "120"},
            ],
        },
        {
            "name": "fibonacci",
            "description": (
                "Return the nth Fibonacci number (0-indexed). "
                "fibonacci(0) returns 0, fibonacci(1) returns 1."
            ),
            "signature": "(n: int) -> int",
            "train_evals": [
                {"input": "(0)", "output": "0"},
                {"input": "(6)", "output": "8"},
            ],
        },
    ],
}


@pytest.mark.llm
@pytest.mark.timeout(600)
class TestLLMRunSession:
    """Full run_fit flow: spec YAML → profiles → all functions → session."""

    @patch("crucis.core.loop.prompt_adversarial_review", return_value=True)
    @patch("crucis.core.loop.prompt_user_review")
    def test_run_fit_completes_all_functions(self, mock_review, _, tmp_path):
        """Test that run_fit processes every function from a spec file.

        Args:
            mock_review: Mocked prompt_user_review to auto-approve.
            _: Mocked prompt_adversarial_review (auto-accept).
            tmp_path: Pytest tmp_path fixture for temp files.
        """
        _skip_if_no_claude()
        mock_review.side_effect = lambda source, **kwargs: (True, source)

        # Write spec YAML
        objective_path = tmp_path / "spec.yaml"
        objective_path.write_text(yaml.dump(_E2E_SPEC), encoding="utf-8")

        # Use the real profiles file
        profiles_path = Path(__file__).resolve().parents[2] / "constraints" / "profiles.yaml"
        checkpoint_path = tmp_path / ".checkpoint.json"

        state = run_fit(objective_path, profiles_path, checkpoint_path)

        # All functions should be done
        assert len(state.task_progress) == 2
        for progress in state.task_progress:
            assert (
                progress.status == TrainingStatus.complete
            ), f"{progress.name} not done: {progress.status}"
            assert progress.train_suite_source is not None
            assert len(progress.train_suite_source) > 0
            assert progress.adversarial_report is not None

        # Session file should exist
        assert checkpoint_path.exists()
