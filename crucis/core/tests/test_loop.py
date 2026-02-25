"""Tests for Crucis training loop helpers."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from crucis.config import Config
from crucis.core.loop import (
    _build_holdout_eval_test_source,
    _check_implementation_constraints,
    _collect_existing_test_paths,
    _collect_holdout_eval_specs,
    _module_candidates_from_targets,
    _objective_for_task,
    _read_task_context_files,
    _run_pytest_targets,
    _validate_task_names,
    _verify_tests,
    process_task,
    run_evaluation,
    run_fit,
)
from crucis.models import (
    AdversarialReport,
    CheckpointState,
    ConstraintSet,
    ParsedObjective,
    TaskConstraints,
    TaskObjective,
    TaskProgress,
    TrainingStatus,
    VerificationGranularity,
)
from crucis.persistence.policy import OptimizerPolicy


def _fake_proc(returncode: int, stderr_text: str = ""):
    """Create a fake Popen process object for tests.

    Args:
        returncode: Process exit code.
        stderr_text: Text to yield from stderr iteration.

    Returns:
        Object with stderr, returncode, and wait() matching Popen interface.
    """
    proc = type("FakeProc", (), {
        "returncode": returncode,
        "stderr": iter(stderr_text.splitlines(keepends=True)) if stderr_text else iter([]),
        "wait": lambda self: None,
    })()
    return proc


def _constraints() -> TaskConstraints:
    """constraints.

    Returns:
        Computed text result for this operation.
    """
    return TaskConstraints(
        primary={},  # type: ignore[arg-type]
        secondary={},  # type: ignore[arg-type]
        target_files=["src/add.py"],
        guidance=[],
    )


def _config() -> Config:
    """config.

    Returns:
        Result of `_config`.
    """
    return Config(max_iterations=2)


def _objective() -> ParsedObjective:
    """objective.

    Returns:
        Result of `_objective`.
    """
    return ParsedObjective(
        name="add",
        description="Add two numbers",
        train_evals=[{"input": "(1, 2)", "output": "3"}],
        holdout_evals=[{"input": "(5, 7)", "output": "12"}],
        target_files=["src/add.py"],
        tasks=[
            TaskObjective(
                name="add",
                train_evals=[{"input": "(2, 3)", "output": "5"}],
                holdout_evals=[{"input": "(9, 1)", "output": "10"}],
                target_files=["src/task_add.py"],
            )
        ],
    )


def test_module_candidates_from_targets_includes_src_variant():
    """Module candidate derivation should include stripped src variant."""
    result = _module_candidates_from_targets(["src/add.py"])
    assert "src.add" in result
    assert "add" in result


def test_build_holdout_eval_test_source_contains_assertions():
    """Holdout source should include one assertion per holdout case."""
    source = _build_holdout_eval_test_source(_objective_for_task(_objective(), "add"))
    assert "def test_holdout_case_0" in source
    assert "assert TARGET_FUNC" in source


def test_objective_for_task_prefers_task_level_evals():
    """Task-level evals should override top-level evals when present."""
    resolved = _objective_for_task(_objective(), "add")
    assert resolved.train_evals[0].input == "(2, 3)"
    assert resolved.holdout_evals[0].input == "(9, 1)"
    assert resolved.target_files == ["src/task_add.py"]


def test_objective_for_task_falls_back_to_top_level_when_missing():
    """Top-level evals should be used when task-specific evals are absent."""
    objective = ParsedObjective(
        name="math",
        description="math",
        train_evals=[{"input": "(1, 1)", "output": "2"}],
        holdout_evals=[{"input": "(2, 2)", "output": "4"}],
        tasks=[TaskObjective(name="sum")],
    )
    resolved = _objective_for_task(objective, "sum")
    assert resolved.train_evals[0].input == "(1, 1)"
    assert resolved.holdout_evals[0].input == "(2, 2)"
    assert resolved.target_files == []


def test_validate_task_names_accepts_single_objective_name():
    """Single-objective specs should accept --task=<objective-name> filters."""
    objective = ParsedObjective(name="add", description="Add numbers")
    _validate_task_names(objective, ["add"])


def test_validate_task_names_rejects_unknown_for_single_objective():
    """Single-objective specs should reject unknown --task filters."""
    objective = ParsedObjective(name="add", description="Add numbers")
    try:
        _validate_task_names(objective, ["subtract"])
    except ValueError as exc:
        assert "Unknown task(s): subtract. Known: add" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown task filter")


@patch("crucis.core.loop._run_pytest_targets")
def test_verify_tests_redacts_holdout_literals(mock_run_pytest, tmp_path):
    """Holdout failure feedback should not leak hidden case literals.

    Args:
        mock_run_pytest: Mock object for `run_pytest` interactions.
        tmp_path: Temporary directory provided by pytest.
    """
    mock_run_pytest.side_effect = [
        (True, "public pass"),
        (False, "FAILED test_holdout_add.py::test_holdout_case_0 - assert 1 == 999"),
    ]
    holdout_spec = ParsedObjective(
        name="add",
        description="Add",
        holdout_evals=[{"input": "(1, 998)", "output": "999"}],
        target_files=["src/add.py"],
    )

    passed, feedback = _verify_tests(
        test_dir=tmp_path / "tests",
        use_sandbox=False,
        holdout_specs={"add": holdout_spec},
    )
    assert passed is False
    assert "holdout cases failed" in feedback.lower()
    assert "test_holdout_case_0: FAILED" in feedback
    assert "998" not in feedback
    assert "999" not in feedback


@patch("crucis.core.loop._run_pytest_targets")
def test_verify_tests_surfaces_holdout_config_error(mock_run_pytest, tmp_path):
    """Config errors should be returned verbatim (non-redacted).

    Args:
        mock_run_pytest: Mock object for `run_pytest` interactions.
        tmp_path: Temporary directory provided by pytest.
    """
    mock_run_pytest.side_effect = [
        (True, "public pass"),
        (False, "HOLDOUT EVAL CONFIG ERROR: bad target_files"),
    ]
    holdout_spec = ParsedObjective(name="add", description="Add")
    passed, feedback = _verify_tests(
        test_dir=tmp_path / "tests",
        use_sandbox=False,
        holdout_specs={"add": holdout_spec},
    )
    assert passed is False
    assert feedback.startswith("HOLDOUT EVAL CONFIG ERROR:")


@patch("crucis.core.loop._run_holdout_eval_checks")
@patch("crucis.core.loop._run_pytest_targets")
def test_verify_tests_task_granularity_aggregates_by_task(
    mock_run_pytest,
    mock_holdout,
    tmp_path,
):
    """Task granularity should verify each task unit separately.

    Args:
        mock_run_pytest: Mock object for `run_pytest` interactions.
        mock_holdout: Mock object for `holdout` interactions.
        tmp_path: Temporary directory provided by pytest.
    """
    test_dir = tmp_path / "tests"
    test_dir.mkdir(parents=True, exist_ok=True)
    (test_dir / "test_add.py").write_text("def test_add(): pass\n", encoding="utf-8")
    (test_dir / "test_sub.py").write_text("def test_sub(): pass\n", encoding="utf-8")

    mock_run_pytest.side_effect = [(True, "ok"), (True, "ok")]
    mock_holdout.return_value = (True, "")

    objective = ParsedObjective(
        name="math",
        description="math",
        verification_granularity=VerificationGranularity.task,
        tasks=[TaskObjective(name="add"), TaskObjective(name="sub")],
    )
    state = CheckpointState(
        task_progress=[
            TaskProgress(name="add", train_suite_source="def test_add(): pass"),
            TaskProgress(name="sub", train_suite_source="def test_sub(): pass"),
        ]
    )

    passed, _feedback = _verify_tests(
        test_dir=test_dir,
        use_sandbox=False,
        state=state,
        objective=objective,
    )
    assert passed is True
    assert mock_run_pytest.call_count == 2


@patch("crucis.core.loop._run_pytest_targets")
def test_verify_tests_objective_granularity_uses_single_public_run(mock_run_pytest, tmp_path):
    """Objective granularity should run one public suite check for the objective.

    Args:
        mock_run_pytest: Mock object for `run_pytest` interactions.
        tmp_path: Temporary directory provided by pytest.
    """
    mock_run_pytest.side_effect = [(True, "public pass")]
    objective = ParsedObjective(
        name="math",
        description="math",
        verification_granularity=VerificationGranularity.objective,
    )
    state = CheckpointState(task_progress=[TaskProgress(name="math", train_suite_source="x")])

    passed, _feedback = _verify_tests(
        test_dir=tmp_path / "tests",
        use_sandbox=False,
        state=state,
        objective=objective,
    )
    assert passed is True
    assert mock_run_pytest.call_count == 1


def test_verify_tests_task_granularity_missing_task_file_fails(tmp_path):
    """Task mode should fail explicitly when a verifier unit file is missing.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective = ParsedObjective(
        name="math",
        description="math",
        verification_granularity=VerificationGranularity.task,
        tasks=[TaskObjective(name="add")],
    )
    state = CheckpointState(
        task_progress=[TaskProgress(name="add", train_suite_source="def test_add(): pass")]
    )

    passed, feedback = _verify_tests(
        test_dir=tmp_path / "tests",
        use_sandbox=False,
        state=state,
        objective=objective,
    )
    assert passed is False
    assert "verification unit" in feedback.lower()
    assert "missing test suite file" in feedback.lower()


def test_verify_tests_task_granularity_invalid_task_name_reports_config_error(tmp_path):
    """Task mode should surface invalid verifier-unit names as config errors.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective = ParsedObjective(
        name="math",
        description="math",
        verification_granularity=VerificationGranularity.task,
        tasks=[TaskObjective(name="good_name")],
    )
    state = CheckpointState(
        task_progress=[TaskProgress(name="bad-name", train_suite_source="def test_x(): pass")]
    )

    passed, feedback = _verify_tests(
        test_dir=tmp_path / "tests",
        use_sandbox=False,
        state=state,
        objective=objective,
    )
    assert passed is False
    assert feedback.startswith("EVALUATION CONFIG ERROR:")


@patch(
    "crucis.core.loop.subprocess.run",
    side_effect=subprocess.TimeoutExpired(cmd=["pytest"], timeout=120),
)
def test_run_pytest_targets_returns_timeout_feedback(_mock_run, tmp_path):
    """Host pytest timeout should return actionable failure feedback.

    Args:
        _mock_run: Unused mock fixture placeholder for subprocess invocation.
        tmp_path: Temporary directory provided by pytest.
    """
    passed, output = _run_pytest_targets(
        workspace=tmp_path,
        targets=[tmp_path / "tests"],
        use_sandbox=False,
        timeout_sec=120,
    )

    assert passed is False
    assert "timed out after 120s" in output


@patch("crucis.core.loop.subprocess.run")
def test_run_pytest_targets_uses_python_module_and_workspace_env(mock_run, tmp_path):
    """Host pytest should run via interpreter module mode with workspace import path.

    Args:
        mock_run: Mock object for subprocess invocation.
        tmp_path: Temporary directory provided by pytest.
    """
    mock_run.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    passed, _output = _run_pytest_targets(
        workspace=tmp_path,
        targets=[tmp_path / "tests"],
        use_sandbox=False,
    )

    assert passed is True
    args, kwargs = mock_run.call_args
    assert args[0][:3] == [sys.executable, "-m", "pytest"]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["env"]["PYTHONPATH"].split(os.pathsep)[0] == str(tmp_path)


@patch("crucis.core.loop.subprocess.run")
def test_run_evaluation_fails_fast_on_invalid_task_name(mock_run, tmp_path):
    """Evaluation should fail before agent execution on invalid task names.

    Args:
        mock_run: Mock object for `run` interactions.
        tmp_path: Temporary directory provided by pytest.
    """
    state = CheckpointState(
        task_progress=[
            TaskProgress(
                name="bad-task",
                status=TrainingStatus.complete,
                train_suite_source="def test_add():\n    assert True",
            )
        ]
    )

    passed = run_evaluation(state, _config(), test_dir=tmp_path / "tests")
    assert passed is False
    assert mock_run.call_count == 0


@patch("crucis.core.loop._verify_tests", return_value=(True, ""))
@patch(
    "crucis.core.loop.build_implementation_command",
    side_effect=lambda prompt, _a, _m: ["agent", prompt],
)
@patch("crucis.core.loop.Popen")
def test_run_evaluation_retries_after_agent_failure(
    mock_popen, _mock_build_cmd, _mock_verify, tmp_path
):
    """Evaluation should retry when agent command fails, then continue.

    Args:
        mock_popen: Mock object for Popen interactions.
        _mock_build_cmd: Unused mock fixture placeholder for `build_cmd`.
        _mock_verify: Unused mock fixture placeholder for `verify`.
        tmp_path: Temporary directory provided by pytest.
    """
    mock_popen.side_effect = [
        _fake_proc(returncode=1, stderr_text="broken"),
        _fake_proc(returncode=0),
    ]

    state = CheckpointState(
        task_progress=[
            TaskProgress(
                name="add",
                status=TrainingStatus.complete,
                train_suite_source="def test_add():\n    assert add(1,2)==3",
            )
        ]
    )
    passed = run_evaluation(state, _config(), test_dir=tmp_path / "tests")
    assert passed is True
    assert mock_popen.call_count == 2


@patch("crucis.core.loop.prompt_adversarial_review", return_value=True)
@patch("crucis.core.loop.run_adversarial_probe", return_value=(True, "def add(a,b): return 3"))
@patch("crucis.core.loop.run_adversarial_review")
@patch(
    "crucis.core.loop.prompt_user_review",
    return_value=(True, "def test_add():\n    assert add(1,2)==3"),
)
@patch("crucis.core.loop.run_cli_agent")
def test_process_task_sets_complete_and_probe_fields(
    mock_run_cli,
    _mock_review,
    mock_adversarial_review,
    _mock_probe,
    _mock_prompt,
):
    """Task processing should finish complete and attach probe data to report.

    Args:
        mock_run_cli: Mock object for `run_cli` interactions.
        _mock_review: Unused mock fixture placeholder for `review`.
        mock_adversarial_review: Mock object for `adversarial_review` interactions.
        _mock_probe: Unused mock fixture placeholder for `probe`.
        _mock_prompt: Unused mock fixture placeholder for `prompt`.
    """
    mock_run_cli.return_value = type(
        "R",
        (),
        {
            "exit_code": 0,
            "stdout": "```python\ndef test_add():\n    assert add(1,2)==3\n```",
            "stderr": "",
        },
    )()
    mock_adversarial_review.return_value = AdversarialReport(
        attack_vectors=["hardcoded outputs"],
        generalization_gaps=["no large numbers"],
        suggested_probe_tests=["randomized cases"],
        correctness_issues=[],
    )

    progress = process_task("add", _objective(), _constraints(), _config())
    assert progress.status == TrainingStatus.complete
    assert progress.adversarial_report is not None
    assert progress.adversarial_report.probe_succeeded is True


def test_collect_holdout_eval_specs_only_includes_tasks_with_holdouts():
    """Only tasks with holdout evals should be collected for final checks."""
    objective = ParsedObjective(
        name="root",
        description="root",
        tasks=[
            TaskObjective(name="a", holdout_evals=[{"input": "(1)", "output": "1"}]),
            TaskObjective(name="b"),
        ],
    )
    state = CheckpointState(
        task_progress=[
            TaskProgress(name="a", train_suite_source="def test_a(): pass"),
            TaskProgress(name="b", train_suite_source="def test_b(): pass"),
        ]
    )
    result = _collect_holdout_eval_specs(state, objective)
    assert list(result.keys()) == ["a"]


@patch("crucis.core.loop._enqueue_optimizer_job")
@patch("crucis.core.loop._verify_tests", return_value=(True, ""))
@patch(
    "crucis.core.loop.build_implementation_command",
    side_effect=lambda prompt, _a, _m: ["agent", prompt],
)
@patch("crucis.core.loop.Popen")
def test_run_evaluation_enqueues_background_job_on_completion(
    mock_popen,
    _mock_build_cmd,
    _mock_verify,
    mock_enqueue,
    tmp_path,
):
    """Successful evaluation should enqueue background optimization once.

    Args:
        mock_popen: Mock object for Popen interactions.
        _mock_build_cmd: Unused mock fixture placeholder for `build_cmd`.
        _mock_verify: Unused mock fixture placeholder for `verify`.
        mock_enqueue: Mock object for `enqueue` interactions.
        tmp_path: Temporary directory provided by pytest.
    """
    mock_popen.return_value = _fake_proc(returncode=0)
    state = CheckpointState(
        task_progress=[
            TaskProgress(
                name="add",
                status=TrainingStatus.complete,
                train_suite_source="def test_add():\n    assert add(1,2)==3",
            )
        ]
    )

    passed = run_evaluation(
        state,
        _config(),
        test_dir=tmp_path / "tests",
        objective=_objective(),
        use_sandbox=False,
    )
    assert passed is True
    assert mock_enqueue.call_count == 1
    assert mock_enqueue.call_args.kwargs["trigger"] == "evaluate"


@patch("crucis.core.loop._enqueue_optimizer_job")
@patch("crucis.core.loop.process_task")
@patch("crucis.core.loop._load_policy_or_none")
def test_run_fit_passes_active_policy_to_task_processing(
    mock_load_policy,
    mock_process_task,
    _mock_enqueue,
    tmp_path,
):
    """Fit should load active policy and thread it into task processing.

    Args:
        mock_load_policy: Mock object for `load_policy` interactions.
        mock_process_task: Mock object for `process_task` interactions.
        _mock_enqueue: Unused mock fixture placeholder for `enqueue`.
        tmp_path: Temporary directory provided by pytest.
    """
    objective_path = tmp_path / "objective.yaml"
    objective_path.write_text(
        "\n".join(
            [
                "name: add",
                "description: Add two numbers",
                "target_files:",
                "  - src/add.py",
                "train_evals:",
                '  - input: "(1, 2)"',
                '    output: "3"',
            ]
        ),
        encoding="utf-8",
    )
    constraints_dir = tmp_path / "constraints"
    constraints_dir.mkdir(parents=True, exist_ok=True)
    (constraints_dir / "profiles.yaml").write_text(
        "profiles:\n  default: {}\n",
        encoding="utf-8",
    )

    policy = OptimizerPolicy(repository_skill="repo-skill")
    mock_load_policy.return_value = policy
    mock_process_task.return_value = TaskProgress(
        name="add",
        status=TrainingStatus.complete,
        train_suite_source="def test_add():\n    assert add(1,2)==3\n",
    )

    run_fit(
        objective_path=objective_path,
        profiles_path=Path("constraints/profiles.yaml"),
        checkpoint_path=tmp_path / ".checkpoint.json",
    )

    assert mock_process_task.call_count == 1
    assert mock_process_task.call_args.kwargs["policy"] == policy
    assert _mock_enqueue.call_count == 1
    assert (
        _mock_enqueue.call_args.kwargs["profiles_path"]
        == (tmp_path / "constraints" / "profiles.yaml").resolve()
    )


def test_objective_for_task_copies_both_constraint_profiles():
    """Task-scoped objective should carry both constraint profile fields."""
    objective = ParsedObjective(
        name="math",
        description="math",
        tests_constraint_profile="strict",
        implementation_constraint_profile="default",
        tasks=[
            TaskObjective(
                name="add",
                tests_constraint_profile="recommended",
                implementation_constraint_profile="strict",
            ),
        ],
    )
    resolved = _objective_for_task(objective, "add")
    assert resolved.tests_constraint_profile == "recommended"
    assert resolved.implementation_constraint_profile == "strict"


def test_objective_for_task_falls_back_to_objective_profiles():
    """Task without profiles should inherit from objective level."""
    objective = ParsedObjective(
        name="math",
        description="math",
        tests_constraint_profile="strict",
        implementation_constraint_profile="recommended",
        tasks=[TaskObjective(name="add")],
    )
    resolved = _objective_for_task(objective, "add")
    assert resolved.tests_constraint_profile == "strict"
    assert resolved.implementation_constraint_profile == "recommended"


def test_check_implementation_constraints_passes_clean_code(tmp_path):
    """Clean implementation code should pass constraint checks.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "add.py").write_text(
        'def add(a, b):\n    """Add two numbers."""\n    return a + b\n',
        encoding="utf-8",
    )

    constraints_map = {
        "add": TaskConstraints(
            primary=ConstraintSet(max_lines_per_function=50),
            secondary=ConstraintSet(),
            target_files=["src/add.py"],
        ),
    }

    passed, feedback = _check_implementation_constraints(tmp_path, constraints_map)
    assert passed is True
    assert feedback == ""


def test_check_implementation_constraints_fails_on_violation(tmp_path):
    """Implementation constraints should fail when code exceeds limits.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    long_body = "\n".join(f"    x{i} = {i}" for i in range(60))
    (src_dir / "add.py").write_text(
        f"def add(a, b):\n{long_body}\n    return a + b\n",
        encoding="utf-8",
    )

    constraints_map = {
        "add": TaskConstraints(
            primary=ConstraintSet(max_lines_per_function=10),
            secondary=ConstraintSet(),
            target_files=["src/add.py"],
        ),
    }

    passed, feedback = _check_implementation_constraints(tmp_path, constraints_map)
    assert passed is False
    assert "add" in feedback
    assert "violation" in feedback.lower()


def test_check_implementation_constraints_skips_missing_files(tmp_path):
    """Missing target files should be silently skipped.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    constraints_map = {
        "add": TaskConstraints(
            primary=ConstraintSet(max_lines_per_function=10),
            secondary=ConstraintSet(),
            target_files=["src/nonexistent.py"],
        ),
    }

    passed, feedback = _check_implementation_constraints(tmp_path, constraints_map)
    assert passed is True
    assert feedback == ""


@patch("crucis.core.loop._check_implementation_constraints", return_value=(False, "too complex"))
@patch("crucis.core.loop._verify_tests", return_value=(True, ""))
@patch(
    "crucis.core.loop.build_implementation_command",
    side_effect=lambda prompt, _a, _m: ["agent", prompt],
)
@patch("crucis.core.loop.Popen")
def test_run_evaluation_retries_on_implementation_constraint_failure(
    mock_popen, _mock_build_cmd, _mock_verify, mock_check_impl, tmp_path
):
    """Evaluation should retry when implementation constraints fail.

    Args:
        mock_popen: Mock object for Popen interactions.
        _mock_build_cmd: Unused mock fixture placeholder for build_cmd.
        _mock_verify: Unused mock fixture placeholder for verify.
        mock_check_impl: Mock for implementation constraint checking.
        tmp_path: Temporary directory provided by pytest.
    """
    mock_popen.return_value = _fake_proc(returncode=0)
    mock_check_impl.side_effect = [
        (False, "too complex"),
        (True, ""),
    ]

    state = CheckpointState(
        task_progress=[
            TaskProgress(
                name="add",
                status=TrainingStatus.complete,
                train_suite_source="def test_add():\n    assert add(1,2)==3",
            )
        ]
    )

    impl_map = {"add": TaskConstraints(
        primary={}, secondary={}, target_files=["src/add.py"], guidance=[],  # type: ignore[arg-type]
    )}
    passed = run_evaluation(
        state,
        _config(),
        test_dir=tmp_path / "tests",
        implementation_constraints_map=impl_map,
    )
    assert passed is True
    assert mock_check_impl.call_count == 2
    assert mock_popen.call_count == 2


def test_read_task_context_files_aggregates_objective_and_task_level(tmp_path):
    """Context reader should merge objective-level and task-level context_files.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    (tmp_path / "a.py").write_text("A = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("B = 2\n", encoding="utf-8")

    objective = ParsedObjective(
        name="calc",
        description="calc",
        context_files=["a.py"],
        tasks=[TaskObjective(name="add", context_files=["b.py"])],
    )
    result = _read_task_context_files(objective, tmp_path)
    assert "a.py" in result
    assert "b.py" in result


def test_read_task_context_files_returns_empty_without_workspace():
    """Context reader should return empty dict when workspace is None."""
    objective = ParsedObjective(
        name="calc", description="calc", context_files=["a.py"]
    )
    result = _read_task_context_files(objective, None)
    assert result == {}


def test_read_task_context_files_returns_empty_when_no_context_files():
    """Context reader should return empty dict when no context_files are set."""
    objective = ParsedObjective(name="calc", description="calc")
    result = _read_task_context_files(objective, Path("/tmp"))
    assert result == {}


def test_collect_existing_test_paths_finds_existing_files(tmp_path):
    """Collector should return paths for files that exist on disk.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_a.py").write_text("pass\n", encoding="utf-8")

    objective = ParsedObjective(
        name="calc",
        description="calc",
        existing_tests=["tests/test_a.py", "tests/test_missing.py"],
    )
    result = _collect_existing_test_paths(objective, tmp_path)
    assert len(result) == 1
    assert result[0] == tmp_path / "tests" / "test_a.py"


def test_collect_existing_test_paths_deduplicates(tmp_path):
    """Collector should not return duplicate paths from objective and tasks.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_shared.py").write_text("pass\n", encoding="utf-8")

    objective = ParsedObjective(
        name="calc",
        description="calc",
        existing_tests=["tests/test_shared.py"],
        tasks=[TaskObjective(name="add", existing_tests=["tests/test_shared.py"])],
    )
    result = _collect_existing_test_paths(objective, tmp_path)
    assert len(result) == 1


@patch("crucis.core.loop._collect_existing_test_paths")
@patch("crucis.core.loop._run_pytest_targets")
@patch("crucis.core.loop._verify_tests", return_value=(True, ""))
@patch(
    "crucis.core.loop.build_implementation_command",
    side_effect=lambda prompt, _a, _m: ["agent", prompt],
)
@patch("crucis.core.loop.Popen")
def test_run_evaluation_regression_gate_retries_on_failure(
    mock_popen,
    _mock_build_cmd,
    _mock_verify,
    mock_pytest,
    mock_collect,
    tmp_path,
):
    """Evaluation should retry when existing tests fail as regression gate.

    Args:
        mock_popen: Mock for Popen interactions.
        _mock_build_cmd: Unused mock for build_cmd.
        _mock_verify: Unused mock for verify.
        mock_pytest: Mock for _run_pytest_targets.
        mock_collect: Mock for _collect_existing_test_paths.
        tmp_path: Temporary directory provided by pytest.
    """
    mock_popen.return_value = _fake_proc(returncode=0)
    mock_collect.return_value = [tmp_path / "tests" / "test_existing.py"]
    mock_pytest.side_effect = [
        (False, "FAILED test_existing.py"),
        (True, "all passed"),
    ]

    state = CheckpointState(
        task_progress=[
            TaskProgress(
                name="add",
                status=TrainingStatus.complete,
                train_suite_source="def test_add():\n    assert add(1,2)==3",
            )
        ]
    )
    passed = run_evaluation(
        state,
        _config(),
        test_dir=tmp_path / "tests",
        objective=_objective(),
    )
    assert passed is True
    assert mock_popen.call_count == 2
    assert mock_pytest.call_count == 2


@patch("crucis.core.loop._collect_existing_test_paths")
@patch("crucis.core.loop._verify_tests", return_value=(True, ""))
@patch(
    "crucis.core.loop.build_implementation_command",
    side_effect=lambda prompt, _a, _m: ["agent", prompt],
)
@patch("crucis.core.loop.Popen")
def test_run_evaluation_skips_regression_gate_when_no_existing_tests(
    mock_popen,
    _mock_build_cmd,
    _mock_verify,
    mock_collect,
    tmp_path,
):
    """Evaluation should skip regression gate when no existing tests are configured.

    Args:
        mock_popen: Mock for Popen interactions.
        _mock_build_cmd: Unused mock for build_cmd.
        _mock_verify: Unused mock for verify.
        mock_collect: Mock for _collect_existing_test_paths.
        tmp_path: Temporary directory provided by pytest.
    """
    mock_popen.return_value = _fake_proc(returncode=0)
    mock_collect.return_value = []

    state = CheckpointState(
        task_progress=[
            TaskProgress(
                name="add",
                status=TrainingStatus.complete,
                train_suite_source="def test_add():\n    assert add(1,2)==3",
            )
        ]
    )
    passed = run_evaluation(
        state,
        _config(),
        test_dir=tmp_path / "tests",
        objective=_objective(),
    )
    assert passed is True
    assert mock_popen.call_count == 1
