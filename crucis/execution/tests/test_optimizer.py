"""Tests for background GEPA optimizer orchestration."""

import json
import os
from pathlib import Path

from crucis.execution.optimizer import (
    AggregatedMetrics,
    BlackboxRunResult,
    OptimizationJob,
    _build_objective_examples,
    _build_task_examples,
    _build_verifier_examples,
    _prepare_isolated_workspace,
    _process_job,
    _score_candidate_on_example,
    _should_promote,
    _target_files_for_example,
    _validate_job_prerequisites,
    enqueue_background_optimization,
    run_optimizer_worker,
)
from crucis.models import CheckpointState, ParsedObjective, TaskObjective, VerificationGranularity
from crucis.persistence.policy import candidate_policy_path, lock_path, queue_dir
from crucis.persistence.settings import load_runtime_settings


def _objective() -> ParsedObjective:
    """objective.

    Returns:
        Result of `_objective`.
    """
    return ParsedObjective(
        name="math",
        description="Math tasks",
        target_files=["src/add.py"],
        tasks=[
            TaskObjective(
                name="add",
                train_evals=[{"input": "(1, 2)", "output": "3"}],
            ),
            TaskObjective(
                name="sub",
                train_evals=[{"input": "(3, 1)", "output": "2"}],
            ),
        ],
    )


def _checkpoint() -> CheckpointState:
    """checkpoint.

    Returns:
        Result of `_checkpoint`.
    """
    return CheckpointState.model_validate(
        {
            "task_progress": [
                {
                    "name": "add",
                    "status": "complete",
                    "train_suite_source": "def test_add():\n    assert add(1,2)==3\n",
                }
            ]
        }
    )


def test_enqueue_background_optimization_writes_queue_job(tmp_path: Path, monkeypatch):
    """Enqueue should persist a job payload under optimizer queue.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture.
    """
    monkeypatch.setattr(
        "crucis.execution.optimizer.spawn_optimizer_worker",
        lambda _workspace: True,
    )

    queued = enqueue_background_optimization(
        workspace=tmp_path,
        objective=_objective(),
        checkpoint=_checkpoint(),
        trigger="fit",
    )
    assert queued is True

    jobs = sorted(queue_dir(tmp_path).glob("*.json"))
    assert len(jobs) == 1
    payload = json.loads(jobs[0].read_text(encoding="utf-8"))
    assert payload["trigger"] == "fit"
    assert "objective_snapshot" in payload
    assert payload["profiles_path"] == str((tmp_path / "constraints" / "profiles.yaml").resolve())


def test_enqueue_background_optimization_uses_custom_profiles_path(tmp_path: Path, monkeypatch):
    """Enqueue should persist the effective profiles path when one is provided.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture.
    """
    monkeypatch.setattr(
        "crucis.execution.optimizer.spawn_optimizer_worker",
        lambda _workspace: True,
    )
    custom_profiles = tmp_path / "constraints" / "alt.yaml"
    custom_profiles.parent.mkdir(parents=True, exist_ok=True)
    custom_profiles.write_text("profiles: {}\n", encoding="utf-8")

    enqueue_background_optimization(
        workspace=tmp_path,
        objective=_objective(),
        checkpoint=_checkpoint(),
        trigger="evaluate",
        profiles_path=custom_profiles,
    )

    jobs = sorted(queue_dir(tmp_path).glob("*.json"))
    payload = json.loads(jobs[0].read_text(encoding="utf-8"))
    assert payload["profiles_path"] == str(custom_profiles.resolve())


def test_run_optimizer_worker_skips_when_lock_exists(tmp_path: Path, monkeypatch):
    """Worker should no-op when another live worker lock already exists.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture.
    """
    monkeypatch.setattr(
        "crucis.execution.optimizer.spawn_optimizer_worker",
        lambda _workspace: True,
    )
    monkeypatch.setattr(
        "crucis.execution.optimizer._pid_command_line",
        lambda _pid: "python -m crucis.gepa_optimizer --workspace x --once",
    )
    enqueue_background_optimization(tmp_path, _objective(), _checkpoint(), "fit")

    lock = lock_path(tmp_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(
        json.dumps({"pid": os.getpid(), "created_at": "2030-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )

    run_optimizer_worker(tmp_path, once=True)
    jobs = sorted(queue_dir(tmp_path).glob("*.json"))
    assert len(jobs) == 1


def test_run_optimizer_worker_recovers_stale_lock(tmp_path: Path, monkeypatch):
    """Worker should reclaim stale lock files and process queued jobs.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture.
    """
    monkeypatch.setattr(
        "crucis.execution.optimizer.spawn_optimizer_worker",
        lambda _workspace: True,
    )
    enqueue_background_optimization(tmp_path, _objective(), _checkpoint(), "fit")

    processed: list[Path] = []

    def _fake_process(_workspace, job_path, _settings):
        """Stub that records processed job paths.

        Args:
            _workspace: Unused workspace path.
            job_path: Path to the job file being processed.
            _settings: Unused runtime settings.
        """
        processed.append(job_path)
        job_path.unlink(missing_ok=True)

    monkeypatch.setattr("crucis.execution.optimizer._process_job_file", _fake_process)

    lock = lock_path(tmp_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(
        json.dumps({"pid": 999999, "created_at": "2026-02-20T00:00:00+00:00"}),
        encoding="utf-8",
    )

    run_optimizer_worker(tmp_path, once=True)
    assert processed
    assert not lock.exists()


def test_run_optimizer_worker_recovers_lock_when_pid_command_mismatch(tmp_path: Path, monkeypatch):
    """Worker should recover lock when PID is alive but command does not match optimizer.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture.
    """
    monkeypatch.setattr(
        "crucis.execution.optimizer.spawn_optimizer_worker",
        lambda _workspace: True,
    )
    enqueue_background_optimization(tmp_path, _objective(), _checkpoint(), "fit")

    processed: list[Path] = []

    def _fake_process(_workspace, job_path, _settings):
        """Stub that records processed job paths.

        Args:
            _workspace: Unused workspace path.
            job_path: Path to the job file being processed.
            _settings: Unused runtime settings.
        """
        processed.append(job_path)
        job_path.unlink(missing_ok=True)

    monkeypatch.setattr("crucis.execution.optimizer._process_job_file", _fake_process)
    monkeypatch.setattr(
        "crucis.execution.optimizer._pid_command_line",
        lambda _pid: "python -m unrelated.worker",
    )

    lock = lock_path(tmp_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(
        json.dumps({"pid": os.getpid(), "created_at": "2030-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )

    run_optimizer_worker(tmp_path, once=True)
    assert processed
    assert not lock.exists()


def test_run_optimizer_worker_emits_single_stop_event_when_lock_held(tmp_path: Path, monkeypatch):
    """Worker logging should emit one stop event when lock is already held.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture.
    """
    events: list[tuple[str, dict]] = []

    class _FakeLogger:
        """Fake event logger."""

        def __init__(self, _workspace, _phase):
            """Initialize fake logger.

            Args:
                _workspace: Unused workspace value.
                _phase: Unused phase value.
            """
            self.path = None

        def emit(self, event, **kwargs):
            """Record emitted events.

            Args:
                event: Event name.
                **kwargs: Event attributes.
            """
            events.append((event, kwargs))

        def close(self):
            """No-op close for fake logger."""

    monkeypatch.setattr("crucis.execution.optimizer.EventLogger", _FakeLogger)
    monkeypatch.setattr(
        "crucis.execution.optimizer._acquire_worker_lock", lambda _workspace: False
    )

    run_optimizer_worker(tmp_path, once=True)
    stop_events = [event for event, _kwargs in events if event == "worker_stopped"]
    assert len(stop_events) == 1


def test_build_task_examples_uses_task_objective_and_checkpoint_suite():
    """Only tasks with approved train suites should become optimization examples."""
    examples = _build_task_examples(_objective(), _checkpoint(), max_examples=10)
    assert len(examples) == 1
    assert examples[0]["task_name"] == "add"
    assert "train_suite_source" in examples[0]


def test_build_task_examples_skips_examples_without_target_files():
    """Task-scoped examples require resolved target files."""
    objective = ParsedObjective(
        name="math",
        description="Math",
        tasks=[TaskObjective(name="add")],
    )
    checkpoint = CheckpointState.model_validate(
        {
            "task_progress": [
                {
                    "name": "add",
                    "status": "complete",
                    "train_suite_source": "def test_add():\n    assert True\n",
                }
            ]
        }
    )
    examples = _build_task_examples(objective, checkpoint, max_examples=10)
    assert examples == []


def test_build_verifier_examples_uses_objective_mode_when_configured():
    """Objective granularity should produce one objective verifier example."""
    objective = _objective().model_copy(
        update={"verification_granularity": VerificationGranularity.objective}
    )
    examples = _build_verifier_examples(objective, _checkpoint(), max_examples=10)
    assert len(examples) == 1
    assert examples[0]["unit_kind"] == "objective"
    assert "train_suite_map" in examples[0]


def test_build_objective_examples_empty_when_no_train_suites():
    """Objective verifier examples require at least one approved train suite."""
    checkpoint = CheckpointState(task_progress=[])
    examples = _build_objective_examples(_objective(), checkpoint, max_examples=10)
    assert examples == []


def test_build_objective_examples_empty_when_no_resolved_target_files():
    """Objective-scoped examples require at least one resolved target file."""
    objective = ParsedObjective(
        name="math",
        description="Math",
        tasks=[TaskObjective(name="add")],
        target_files=[],
    )
    checkpoint = CheckpointState.model_validate(
        {
            "task_progress": [
                {
                    "name": "add",
                    "status": "complete",
                    "train_suite_source": "def test_add():\n    assert True\n",
                }
            ]
        }
    )
    examples = _build_objective_examples(objective, checkpoint, max_examples=10)
    assert examples == []


def test_target_files_for_example_objective_includes_task_files():
    """Objective verifier targeting should include task-level file overrides."""
    objective = ParsedObjective(
        name="math",
        description="Math",
        target_files=["src/base.py"],
        tasks=[TaskObjective(name="add", target_files=["src/add.py"])],
    )
    targets = _target_files_for_example(objective, "objective")
    assert "src/base.py" in targets
    assert "src/add.py" in targets


def test_prepare_isolated_workspace_copies_target_root_and_project_config(tmp_path: Path):
    """Workspace prep should copy target root context plus key config files.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    source_workspace = tmp_path / "source"
    destination_workspace = tmp_path / "destination"

    (source_workspace / "src").mkdir(parents=True, exist_ok=True)
    (source_workspace / "other").mkdir(parents=True, exist_ok=True)

    (source_workspace / "src" / "add.py").write_text(
        "from src.helpers import inc\n", encoding="utf-8"
    )
    (source_workspace / "src" / "helpers.py").write_text(
        "def inc(x):\n    return x + 1\n", encoding="utf-8"
    )
    (source_workspace / "other" / "ignore.py").write_text(
        "def ignore():\n    return None\n", encoding="utf-8"
    )
    (source_workspace / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    _prepare_isolated_workspace(
        source_workspace=source_workspace,
        destination_workspace=destination_workspace,
        target_files=["src/add.py"],
    )

    assert (destination_workspace / "src" / "add.py").exists()
    assert (destination_workspace / "src" / "helpers.py").exists()
    assert not (destination_workspace / "other" / "ignore.py").exists()
    assert (destination_workspace / "pyproject.toml").exists()


def test_prepare_isolated_workspace_copies_root_python_siblings_for_root_target(
    tmp_path: Path,
):
    """Root-level targets should include root Python sibling files.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    source_workspace = tmp_path / "source"
    destination_workspace = tmp_path / "destination"

    source_workspace.mkdir(parents=True, exist_ok=True)
    (source_workspace / "pkg").mkdir(parents=True, exist_ok=True)

    (source_workspace / "main.py").write_text("import helper\n", encoding="utf-8")
    (source_workspace / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source_workspace / "pkg" / "module.py").write_text("VALUE = 2\n", encoding="utf-8")

    _prepare_isolated_workspace(
        source_workspace=source_workspace,
        destination_workspace=destination_workspace,
        target_files=["main.py"],
    )

    assert (destination_workspace / "main.py").exists()
    assert (destination_workspace / "helper.py").exists()
    assert not (destination_workspace / "pkg" / "module.py").exists()


def test_score_candidate_on_example_returns_weighted_score_and_side_info(
    tmp_path: Path, monkeypatch
):
    """Per-example scoring should expose correctness/speed in ASI.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture.
    """
    settings = load_runtime_settings(tmp_path)
    settings.optimizer.evaluator_timeout_sec = 10
    settings.optimizer.pass_weight = 0.9
    settings.optimizer.speed_weight = 0.1

    monkeypatch.setattr(
        "crucis.execution.optimizer._run_blackbox_task",
        lambda **_kwargs: BlackboxRunResult(
            returncode=0,
            stdout="ok",
            stderr="",
            duration_sec=2.0,
        ),
    )

    score, side_info = _score_candidate_on_example(
        workspace=tmp_path,
        candidate={
            "repository_skill": "",
            "generation_directives": "",
            "adversary_directives": "",
            "evaluation_directives": "",
        },
        example={
            "task_name": "add",
            "objective_snapshot": _objective().model_dump(mode="json"),
            "train_suite_source": "def test_add():\n    assert add(1,2)==3\n",
        },
        settings=settings,
    )

    assert score > 0.9
    assert side_info["scores"]["correctness"] == 1.0
    assert side_info["scores"]["speed"] > 0.0
    assert "duration_sec" in side_info


def test_should_promote_requires_delta_and_non_regression():
    """Promotion gate should enforce score gain and correctness non-regression."""
    baseline = AggregatedMetrics(0.80, 0.90, 0.20, 5)
    better = AggregatedMetrics(0.83, 0.90, 0.30, 5)
    worse_correctness = AggregatedMetrics(0.90, 0.80, 0.90, 5)

    assert _should_promote(baseline, better, min_score_delta=0.01) is True
    assert _should_promote(baseline, better, min_score_delta=0.05) is False
    assert _should_promote(baseline, worse_correctness, min_score_delta=0.01) is False


def test_process_job_reports_missing_gepa_dependency(tmp_path: Path, monkeypatch):
    """Missing GEPA dependency should return failed outcome without raising.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        None.
    """
    job = OptimizationJob(
        job_id="job-1",
        trigger="fit",
        created_at="2026-02-20T00:00:00+00:00",
        objective_snapshot=_objective().model_dump(mode="json"),
        checkpoint_snapshot=_checkpoint().model_dump(mode="json"),
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    settings = load_runtime_settings(tmp_path)
    (tmp_path / "constraints").mkdir(parents=True, exist_ok=True)
    (tmp_path / "constraints" / "profiles.yaml").write_text("profiles: {}\n", encoding="utf-8")

    monkeypatch.setattr("crucis.execution.optimizer._GEPA_AVAILABLE", False)
    monkeypatch.setattr(
        "crucis.execution.optimizer._GEPA_IMPORT_ERROR",
        ImportError("gepa missing"),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    outcome = _process_job(tmp_path, job, run_dir, settings)
    assert outcome["state"] == "failed"
    assert "GEPA dependencies unavailable" in outcome["message"]


def test_process_job_manual_mode_writes_candidate_without_auto_promotion(
    tmp_path: Path, monkeypatch
):
    """Manual promotion mode should keep candidate as artifact without updating active policy.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        None.
    """
    job = OptimizationJob(
        job_id="job-manual",
        trigger="fit",
        created_at="2026-02-20T00:00:00+00:00",
        objective_snapshot=_objective().model_dump(mode="json"),
        checkpoint_snapshot=_checkpoint().model_dump(mode="json"),
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    settings = load_runtime_settings(tmp_path)
    settings.optimizer.promotion_mode = "manual"
    (tmp_path / "constraints").mkdir(parents=True, exist_ok=True)
    (tmp_path / "constraints" / "profiles.yaml").write_text("profiles: {}\n", encoding="utf-8")

    monkeypatch.setattr(
        "crucis.execution.optimizer._build_verifier_examples",
        lambda *_args, **_kwargs: [
            {
                "unit_kind": "task",
                "task_name": "add",
                "objective_snapshot": _objective().model_dump(mode="json"),
                "train_suite_source": "x",
            }
        ],
    )
    monkeypatch.setattr(
        "crucis.execution.optimizer._evaluate_policy_on_examples",
        lambda **_kwargs: AggregatedMetrics(0.5, 0.5, 0.5, 1)
        if _kwargs["policy"].repository_skill == ""
        else AggregatedMetrics(0.9, 1.0, 0.5, 1),
    )

    class DummyResult:
        """DummyResult class."""

        def __init__(self):
            """Set up dummy result with a fixed best_candidate dict."""
            self.best_candidate = {
                "repository_skill": "new-skill",
                "generation_directives": "g",
                "adversary_directives": "a",
                "evaluation_directives": "e",
            }

    def fake_optimize_anything(**_kwargs):
        """Fake optimize anything.

        Args:
            **_kwargs: Unused parameter placeholder required by the call signature.

        Returns:
            Result of `fake_optimize_anything`.
        """
        return DummyResult()

    monkeypatch.setattr("crucis.execution.optimizer._GEPA_AVAILABLE", True)
    monkeypatch.setattr("crucis.execution.optimizer.optimize_anything", fake_optimize_anything)
    monkeypatch.setattr("crucis.execution.optimizer.EngineConfig", lambda **_kw: None)
    monkeypatch.setattr("crucis.execution.optimizer.ReflectionConfig", lambda **_kw: None)
    monkeypatch.setattr("crucis.execution.optimizer.GEPAConfig", lambda **_kw: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    outcome = _process_job(tmp_path, job, run_dir, settings)
    assert outcome["state"] == "completed"
    assert outcome["promoted"] is False
    assert outcome["candidate_ready"] is True
    assert candidate_policy_path(tmp_path, "job-manual").exists()


def test_process_job_fails_fast_when_profiles_path_missing(tmp_path: Path):
    """Optimizer jobs should fail with an explicit message when profiles file is missing.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    job = OptimizationJob(
        job_id="job-missing-profiles",
        trigger="fit",
        created_at="2026-02-20T00:00:00+00:00",
        objective_snapshot=_objective().model_dump(mode="json"),
        checkpoint_snapshot=_checkpoint().model_dump(mode="json"),
        profiles_path=str((tmp_path / "constraints" / "missing.yaml").resolve()),
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    settings = load_runtime_settings(tmp_path)

    outcome = _process_job(tmp_path, job, run_dir, settings)
    assert outcome["state"] == "failed"
    assert "Profiles file not found for optimizer run" in outcome["message"]


def test_validate_job_prerequisites_fails_fast_when_reflection_key_missing(
    tmp_path: Path,
    monkeypatch,
):
    """Optimizer should fail quickly when reflection LM auth key is missing.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture.
    """
    job = OptimizationJob(
        job_id="job-missing-key",
        trigger="fit",
        created_at="2026-02-20T00:00:00+00:00",
        objective_snapshot=_objective().model_dump(mode="json"),
        checkpoint_snapshot=_checkpoint().model_dump(mode="json"),
    )
    settings = load_runtime_settings(tmp_path)
    settings.optimizer.reflection_lm = "openai/gpt-5.1"
    (tmp_path / "constraints").mkdir(parents=True, exist_ok=True)
    (tmp_path / "constraints" / "profiles.yaml").write_text("profiles: {}\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("crucis.execution.optimizer._GEPA_AVAILABLE", True)

    failure = _validate_job_prerequisites(tmp_path, job, settings)
    assert failure is not None
    assert failure["state"] == "failed"
    assert "OPENAI_API_KEY" in failure["message"]
