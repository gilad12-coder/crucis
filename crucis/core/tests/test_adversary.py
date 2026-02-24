"""Tests for adversary prompt and parsing helpers."""

import sys
from unittest.mock import patch

from crucis.config import Config
from crucis.core.adversary import (
    _run_probe_pytest,
    parse_adversarial_report,
    run_adversarial_probe,
)
from crucis.core.prompts import build_adversary_prompt
from crucis.models import CLIResult, ParsedObjective, TrainEval

SAMPLE_TEST_SOURCE = """
import pytest

def test_add_positive():
    assert add(1, 2) == 3
"""


def _spec() -> ParsedObjective:
    """spec.

    Returns:
        Result of `_spec`.
    """
    return ParsedObjective(
        name="add",
        description="Add two integers",
        train_evals=[TrainEval(input="(1, 2)", output="3")],
    )


def _config() -> Config:
    """config.

    Returns:
        Result of `_config`.
    """
    return Config(critic_agent="claude", critic_model="claude-opus-4-6")


def test_build_adversary_prompt_contains_attack_language():
    """Adversary prompt should include exploit-oriented language."""
    prompt = build_adversary_prompt(SAMPLE_TEST_SOURCE, _spec())
    assert "adversary" in prompt.lower()
    assert "cheat" in prompt.lower() or "pass" in prompt.lower()
    assert "attack_vectors" in prompt


def test_parse_adversarial_report_json_object():
    """Valid JSON should parse to a report object."""
    raw = (
        '{"attack_vectors": ["hardcode output"], '
        '"generalization_gaps": ["no negative coverage"], '
        '"suggested_probe_tests": ["add randomized input test"], '
        '"correctness_issues": []}'
    )
    report = parse_adversarial_report(raw)
    assert report.attack_vectors == ["hardcode output"]


@patch("crucis.core.adversary.run_cli_agent")
def test_run_adversarial_probe_success(mock_run):
    """Probe run should return success when generated code passes tests.

    Args:
        mock_run: Mock object for `run` interactions.
    """
    mock_run.return_value = CLIResult(
        stdout="def add(a, b):\n    return 3\n",
        stderr="",
        exit_code=0,
    )
    with patch("crucis.core.adversary._run_probe_pytest", return_value=True):
        passed, code = run_adversarial_probe(SAMPLE_TEST_SOURCE, _spec(), _config())
    assert passed is True
    assert "def add" in code


@patch("crucis.core.adversary.subprocess.run")
def test_run_probe_pytest_uses_python_module_invocation(mock_run):
    """Probe pytest should execute via `python -m pytest` in temp workspace.

    Args:
        mock_run: Mock object for subprocess invocation.
    """
    mock_run.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    test_src = "def test_x():\n    assert True\n"
    impl_src = "def add(a, b):\n    return a + b\n"
    passed = _run_probe_pytest(test_src, impl_src)
    assert passed is True
    args, kwargs = mock_run.call_args
    assert args[0][:3] == [sys.executable, "-m", "pytest"]
    assert kwargs["capture_output"] is True
