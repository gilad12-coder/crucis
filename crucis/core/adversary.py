"""Adversarial review and probe helpers for train suites."""

import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from json_repair import repair_json

from crucis.cli.runner import is_rate_limited, run_cli_agent
from crucis.config import Config
from crucis.core.prompts import build_adversary_prompt, build_probe_prompt
from crucis.core.test_generator import extract_python_from_response
from crucis.defaults import TEXT_ENCODING
from crucis.models import AdversarialReport
from crucis.persistence.audit import log_agent_call
from crucis.persistence.events import EventLogger
from crucis.persistence.policy import OptimizerPolicy


def parse_adversarial_report(raw_json: str) -> AdversarialReport:
    """Parse an adversarial JSON response into an AdversarialReport.

    Args:
        raw_json: Raw model JSON-like output to parse.

    Returns:
        Parsed structured value.
    """
    data = repair_json(raw_json, return_objects=True)
    if not isinstance(data, dict):
        raise ValueError("Adversarial response did not contain a JSON object")
    return AdversarialReport(**data)


def run_adversarial_probe(
    train_suite_source: str,
    objective,
    config: Config,
    policy: OptimizerPolicy | None = None,
    logger: EventLogger | None = None,
    agent_timeout: int | None = None,
) -> tuple[bool, str]:
    """Generate and execute a cheating probe implementation against tests.

    Args:
        train_suite_source: Generated pytest train-suite source code.
        objective: Parsed objective data for the current run.
        config: Runtime configuration values.
        policy: Active optimizer policy used for prompt steering.
        logger: Optional event logger for audit trail.
        agent_timeout: Override for agent subprocess timeout in seconds.

    Returns:
        True when the operation succeeds; otherwise False.
    """
    prompt = build_probe_prompt(train_suite_source, objective, policy=policy)
    timeout_kwargs = {"timeout": agent_timeout} if agent_timeout is not None else {}
    t0 = time.monotonic()
    result = run_cli_agent(
        prompt,
        config.critic_agent,
        config.critic_model,
        config.max_budget_usd,
        **timeout_kwargs,
    )
    duration = time.monotonic() - t0
    log_agent_call(
        logger,
        prompt=prompt,
        result=result,
        agent=config.critic_agent,
        model=config.critic_model,
        budget=config.max_budget_usd,
        duration_sec=duration,
        call_site="run_adversarial_probe",
        task=getattr(objective, "name", None),
    )
    if result.exit_code != 0:
        if is_rate_limited(result.stderr):
            raise RuntimeError("Agent rate-limited by the provider.")
        return False, ""

    try:
        probe_code = extract_python_from_response(result.stdout).strip()
    except (SyntaxError, ValueError):
        return False, ""

    if not probe_code:
        return False, ""

    passed = _run_probe_pytest(train_suite_source, probe_code)
    return passed, probe_code


def run_adversarial_review(
    train_suite_source: str,
    objective,
    config: Config,
    constraints=None,
    policy: OptimizerPolicy | None = None,
    logger: EventLogger | None = None,
    agent_timeout: int | None = None,
) -> AdversarialReport:
    """Run the adversary model on approved tests and parse report output.

    Args:
        train_suite_source: Generated pytest train-suite source code.
        objective: Parsed objective data for the current run.
        config: Runtime configuration values.
        constraints: Resolved constraints for the current task or objective.
        policy: Active optimizer policy used for prompt steering.
        logger: Optional event logger for audit trail.
        agent_timeout: Override for agent subprocess timeout in seconds.

    Returns:
        Result of running the requested operation.
    """
    prompt = build_adversary_prompt(
        train_suite_source,
        objective,
        constraints,
        policy=policy,
    )
    timeout_kwargs = {"timeout": agent_timeout} if agent_timeout is not None else {}
    t0 = time.monotonic()
    result = run_cli_agent(
        prompt,
        config.critic_agent,
        config.critic_model,
        config.max_budget_usd,
        **timeout_kwargs,
    )
    duration = time.monotonic() - t0
    log_agent_call(
        logger,
        prompt=prompt,
        result=result,
        agent=config.critic_agent,
        model=config.critic_model,
        budget=config.max_budget_usd,
        duration_sec=duration,
        call_site="run_adversarial_review",
        task=getattr(objective, "name", None),
    )
    if result.exit_code != 0 and is_rate_limited(result.stderr):
        raise RuntimeError("Agent rate-limited by the provider.")
    return parse_adversarial_report(result.stdout)


def verify_probe_with_holdout_evals(
    probe_code: str,
    func_name: str,
    holdout_evals: list[dict],
) -> bool:
    """Check whether adversarial probe code also passes holdout evals.

    Args:
        probe_code: Probe test source generated by the adversary.
        func_name: Name value for `func_name`.
        holdout_evals: Value for `holdout_evals` used by `verify_probe_with_holdout_evals`.

    Returns:
        True when the operation succeeds; otherwise False.
    """
    if not holdout_evals or not probe_code:
        return False

    lines: list[str] = []
    for idx, case in enumerate(holdout_evals):
        lines.append(f"def test_holdout_{idx}():")
        lines.append(f"    assert {func_name}{case['input']} == {case['output']}")
        lines.append("")
    holdout_test_source = "\n".join(lines)
    return _run_probe_pytest(holdout_test_source, probe_code)


_STDLIB_AND_TEST = frozenset(
    {
        "pytest",
        "unittest",
        "collections",
        "typing",
        "dataclasses",
        "functools",
        "itertools",
        "math",
        "os",
        "sys",
        "re",
        "json",
        "pathlib",
        "abc",
        "enum",
        "copy",
        "operator",
        "random",
        "datetime",
        "decimal",
        "fractions",
        "statistics",
        "string",
        "textwrap",
        "io",
        "contextlib",
        "warnings",
        "types",
    }
)


def _strip_local_imports(train_suite_source: str) -> str:
    """Remove local single-module imports from generated train suite source.

    Args:
        train_suite_source: Generated pytest train-suite source code.

    Returns:
        Computed text result for this operation.
    """
    lines = []
    for line in train_suite_source.splitlines():
        match = re.match(r"^from\s+(\w+)\s+import\s+", line)
        if match and match.group(1) not in _STDLIB_AND_TEST:
            continue
        lines.append(line)
    return "\n".join(lines)


def _run_probe_pytest(train_suite_source: str, probe_code: str) -> bool:
    """Run pytest for generated tests against adversarial probe implementation.

    Args:
        train_suite_source: Generated pytest train-suite source code.
        probe_code: Probe test source generated by the adversary.

    Returns:
        True when the operation succeeds; otherwise False.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        probe_path = temp_path / "probe_impl.py"
        test_path = temp_path / "test_generated.py"

        probe_path.write_text(probe_code, encoding=TEXT_ENCODING)
        cleaned = _strip_local_imports(train_suite_source)
        test_path.write_text(
            "from probe_impl import *\n\n" + cleaned + "\n",
            encoding=TEXT_ENCODING,
        )

        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_path), "-q"],
            cwd=temp_path,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
