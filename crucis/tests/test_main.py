"""Tests for Crucis CLI entrypoint."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from crucis.__main__ import (
    build_parser,
    main,
    run_doctor_command,
    run_evaluate,
    run_init_command,
    run_optimizer_worker_command,
    run_promote,
    show_checkpoint,
)
from crucis.models import CheckpointState, TaskProgress, TrainingStatus
from crucis.persistence.policy import OptimizerStatus


class TestBuildParser:
    """Parser shape tests for new strict command set."""

    def test_run_subcommand_with_objective(self):
        """Test run subcommand with objective path."""
        parser = build_parser()
        args = parser.parse_args(["run", "objective.yaml"])
        assert args.command == "run"
        assert args.objective_path == "objective.yaml"

    def test_status_subcommand(self):
        """Test status subcommand and summary alias."""
        parser = build_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"
        assert args.checkpoint == ".checkpoint.json"
        assert args.json is False

    def test_run_dry_run_flag(self):
        """Test run subcommand --dry-run flag."""
        parser = build_parser()
        args = parser.parse_args(["run", "--dry-run"])
        assert args.command == "run"
        assert args.dry_run is True

    def test_promote_subcommand(self):
        """Test promote subcommand."""
        parser = build_parser()
        args = parser.parse_args(["promote", "--run-id", "run-1"])
        assert args.command == "promote"
        assert args.run_id == "run-1"

    def test_promote_subcommand_force(self):
        """Test promote subcommand force flag."""
        parser = build_parser()
        args = parser.parse_args(["promote", "--run-id", "run-1", "--force"])
        assert args.command == "promote"
        assert args.force is True

    def test_doctor_subcommand(self):
        """Test doctor subcommand."""
        parser = build_parser()
        args = parser.parse_args(["doctor", "--workspace", "."])
        assert args.command == "doctor"
        assert args.workspace == "."
        assert args.json is False

    def test_init_subcommand(self):
        """Test init subcommand defaults."""
        parser = build_parser()
        args = parser.parse_args(["init"])
        assert args.command == "init"
        assert args.workspace == "."
        assert args.name == "my_project"
        assert args.no_agent is False
        assert args.require_agent is False
        assert args.existing_codebase is False
        assert args.with_profiles is False
        assert args.with_settings is False
        assert args.agent is None

    def test_init_subcommand_with_flags(self):
        """Test init subcommand with explicit flags."""
        parser = build_parser()
        args = parser.parse_args(
            [
                "init",
                "--name",
                "foo",
                "--workspace",
                "/tmp",
                "--no-agent",
                "--require-agent",
                "--existing-codebase",
                "--with-profiles",
                "--with-settings",
            ]
        )
        assert args.name == "foo"
        assert args.workspace == "/tmp"
        assert args.no_agent is True
        assert args.require_agent is True
        assert args.existing_codebase is True
        assert args.with_profiles is True
        assert args.with_settings is True

    def test_run_plan_flag(self):
        """Test run --plan flag."""
        parser = build_parser()
        args = parser.parse_args(["run", "objective.yaml", "--plan"])
        assert args.command == "run"
        assert args.plan is True
        assert args.objective_path == "objective.yaml"

    def test_run_force_plan_flag(self):
        """Test run --force-plan flag."""
        parser = build_parser()
        args = parser.parse_args(["run", "--plan", "--force-plan"])
        assert args.force_plan is True

    def test_run_subcommand_defaults(self):
        """Test run subcommand defaults."""
        parser = build_parser()
        args = parser.parse_args(["run", "objective.yaml"])
        assert args.command == "run"
        assert args.objective_path == "objective.yaml"
        assert args.profiles == "constraints/profiles.yaml"
        assert args.checkpoint == ".checkpoint.json"

    def test_run_subcommand_no_path(self):
        """Test run subcommand without objective path."""
        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.command == "run"
        assert args.objective_path is None

    def test_optimizer_worker_subcommand(self):
        """Test optimizer-worker subcommand."""
        parser = build_parser()
        args = parser.parse_args(["optimizer-worker", "--workspace", ".", "--loop", "--json"])
        assert args.command == "optimizer-worker"
        assert args.loop is True
        assert args.json is True


class TestMainDispatch:
    """Dispatch behavior tests for main entrypoint."""

    @patch("crucis.__main__._run_preflight_or_exit")
    @patch("crucis.__main__.run_fit")
    def test_main_run_calls_run_fit(self, mock_run_fit, _mock_preflight, tmp_path):
        """Test main run calls run_fit with auto flags.

        Args:
            mock_run_fit: Mock object for `run_fit` interactions.
            tmp_path: Temporary directory provided by pytest.
        """
        objective = tmp_path / "objective.yaml"
        objective.write_text("name: add\ndescription: Add", encoding="utf-8")
        main(["run", str(objective), "--checkpoint", "cp.json"])
        mock_run_fit.assert_called_once()
        call_kwargs = mock_run_fit.call_args[1]
        assert call_kwargs["auto_tests"] is True
        assert call_kwargs["auto_adversary"] is True
        assert call_kwargs["auto_evaluate"] is True

    @patch("crucis.__main__.load_runtime_settings", side_effect=ValueError("invalid settings"))
    @patch("crucis.__main__.run_fit")
    def test_main_run_exits_when_runtime_settings_invalid(
        self,
        mock_run_fit,
        _mock_load_settings,
        tmp_path,
    ):
        """Run should fail fast when runtime settings cannot be loaded.

        Args:
            mock_run_fit: Mock object for `run_fit` interactions.
            _mock_load_settings: Unused mock for `load_runtime_settings`.
            tmp_path: Temporary directory provided by pytest.
        """
        objective = tmp_path / "objective.yaml"
        objective.write_text("name: add\ndescription: Add", encoding="utf-8")

        with pytest.raises(SystemExit) as exc:
            main(["run", str(objective)])

        assert exc.value.code == 1
        assert mock_run_fit.call_count == 0

    @patch("crucis.__main__._run_preflight_or_exit")
    @patch("crucis.__main__.run_fit")
    def test_main_uses_process_argv_when_argv_is_none(
        self,
        mock_run_fit,
        _mock_preflight,
        tmp_path,
        monkeypatch,
    ):
        """main() should parse sys.argv when argv is omitted.

        Args:
            mock_run_fit: Mock object for `run_fit` interactions.
            tmp_path: Temporary directory provided by pytest.
            monkeypatch: Pytest monkeypatch fixture.
        """
        objective = tmp_path / "objective.yaml"
        objective.write_text("name: add\ndescription: Add", encoding="utf-8")

        monkeypatch.setattr(sys, "argv", ["crucis", "run", str(objective)])
        main()

        mock_run_fit.assert_called_once()

    @patch("crucis.__main__.show_checkpoint")
    def test_main_status_calls_show(self, mock_show):
        """Test main status calls show_checkpoint.

        Args:
            mock_show: Mock object for `show` interactions.
        """
        main(["status", "--checkpoint", "cp.json"])
        mock_show.assert_called_once_with(Path("cp.json"), as_json=False)

    @patch("crucis.__main__.show_checkpoint")
    def test_main_status_json_calls_show(self, mock_show):
        """Test main status --json calls show with JSON mode.

        Args:
            mock_show: Mock object for `show` interactions.
        """
        main(["status", "--checkpoint", "cp.json", "--json"])
        mock_show.assert_called_once_with(Path("cp.json"), as_json=True)

    @patch("crucis.__main__.run_doctor_command")
    def test_main_doctor_calls_run_doctor_command(self, mock_doctor):
        """Doctor command should dispatch to doctor handler.

        Args:
            mock_doctor: Mock object for `doctor` command handler.
        """
        main(["doctor"])
        assert mock_doctor.call_count == 1

    @patch("crucis.__main__.run_optimizer_worker_command")
    def test_main_optimizer_worker_calls_handler(self, mock_worker):
        """Optimizer-worker command should dispatch to worker handler.

        Args:
            mock_worker: Mock object for worker command handler.
        """
        main(["optimizer-worker"])
        assert mock_worker.call_count == 1

    @patch("crucis.__main__.run_init_command")
    def test_main_init_calls_run_init_command(self, mock_init):
        """Init command should dispatch to init handler.

        Args:
            mock_init: Mock object for init command handler.
        """
        main(["init"])
        assert mock_init.call_count == 1

    @patch("crucis.__main__._handle_run_plan")
    def test_main_run_plan_calls_handler(self, mock_plan, tmp_path):
        """Run --plan should dispatch to plan handler.

        Args:
            mock_plan: Mock object for plan handler.
            tmp_path: Temporary directory provided by pytest.
        """
        objective = tmp_path / "objective.yaml"
        objective.write_text("name: add\ndescription: Add", encoding="utf-8")
        main(["run", str(objective), "--plan"])
        assert mock_plan.call_count == 1

    @patch("crucis.__main__.run_promote")
    def test_main_promote_calls_run_promote(self, mock_promote):
        """Test main promote calls run promote.

        Args:
            mock_promote: Mock object for `promote` interactions.
        """
        main(["promote", "--run-id", "run-1"])
        mock_promote.assert_called_once()

    @patch("crucis.__main__._run_preflight_or_exit")
    @patch("crucis.__main__.run_fit")
    def test_run_auto_finds_objective_yaml(self, mock_run_fit, _mock_preflight, tmp_path, monkeypatch):
        """Test run auto-finds objective.yaml in CWD when no path given.

        Args:
            mock_run_fit: Mock object for `run_fit` interactions.
            tmp_path: Temporary directory provided by pytest.
            monkeypatch: Pytest monkeypatch fixture.
        """
        objective = tmp_path / "objective.yaml"
        objective.write_text("name: add\ndescription: Add", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        main(["run", "--checkpoint", "cp.json"])
        mock_run_fit.assert_called_once()


@patch("crucis.__main__.load_checkpoint")
@patch("crucis.__main__.load_runtime_settings", side_effect=ValueError("invalid settings"))
def test_run_evaluate_exits_when_runtime_settings_invalid(
    _mock_load_settings,
    mock_load_checkpoint,
    tmp_path,
):
    """Evaluate should fail fast when runtime settings cannot be loaded.

    Args:
        _mock_load_settings: Unused mock for `load_runtime_settings`.
        mock_load_checkpoint: Mock object for `load_checkpoint` interactions.
        tmp_path: Temporary directory provided by pytest.
    """
    with pytest.raises(SystemExit) as exc:
        run_evaluate(
            objective_path=tmp_path / "objective.yaml",
            profiles_path=Path("constraints/profiles.yaml"),
            checkpoint_path=Path(".checkpoint.json"),
            use_sandbox=False,
        )

    assert exc.value.code == 1
    assert mock_load_checkpoint.call_count == 0


@patch("crucis.__main__.display_checkpoint_table")
@patch("crucis.__main__._load_optimizer_status_if_relevant")
@patch("crucis.__main__.load_checkpoint")
def test_show_checkpoint_passes_optimizer_status(
    mock_load_checkpoint,
    mock_load_optimizer_status,
    mock_display_table,
):
    """Checkpoint display should include optional optimizer status payload.

    Args:
        mock_load_checkpoint: Mock object for `load_checkpoint` interactions.
        mock_load_optimizer_status: Mock object for `load_optimizer_status` interactions.
        mock_display_table: Mock object for `display_table` interactions.
    """
    mock_load_checkpoint.return_value = type("State", (), {"task_progress": []})()
    mock_load_optimizer_status.return_value = OptimizerStatus(state="idle")

    show_checkpoint(Path("cp.json"))
    assert mock_display_table.call_count == 1
    assert "optimizer_status" in mock_display_table.call_args.kwargs


@patch("crucis.__main__._load_optimizer_status_if_relevant", return_value=OptimizerStatus(state="idle"))
@patch("crucis.__main__.load_checkpoint")
def test_show_checkpoint_json_mode_emits_machine_readable_payload(
    mock_load_checkpoint,
    _mock_load_optimizer_status,
    capsys,
):
    """Checkpoint --json mode should emit stable machine-readable structure.

    Args:
        mock_load_checkpoint: Mock object for `load_checkpoint` interactions.
        _mock_load_optimizer_status: Unused mock for optimizer status loading.
        capsys: Pytest capture fixture.
    """
    mock_load_checkpoint.return_value = CheckpointState(
        task_progress=[
            TaskProgress(name="add", status=TrainingStatus.complete, train_suite_source="x"),
            TaskProgress(name="sub", status=TrainingStatus.pending),
        ]
    )

    show_checkpoint(Path("cp.json"), as_json=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["total_tasks"] == 2
    assert payload["summary"]["complete_tasks"] == 1
    assert payload["summary"]["ready_for_evaluation"] is False
    assert len(payload["tasks"]) == 2
    assert payload["optimizer_status"]["state"] == "idle"


@patch("crucis.__main__._is_optimizer_enabled_for_command", return_value=True)
@patch("crucis.__main__.save_optimizer_status")
@patch("crucis.__main__.save_active_policy")
@patch("crucis.__main__.load_optimizer_status")
@patch("crucis.__main__.load_candidate_policy")
def test_run_promote_promotes_candidate_policy(
    mock_load_candidate,
    mock_load_status,
    mock_save_active,
    mock_save_status,
    _mock_gate,
):
    """Promote should load candidate and persist active policy + updated status.

    Args:
        mock_load_candidate: Mock object for `load_candidate` interactions.
        mock_load_status: Mock object for `load_status` interactions.
        mock_save_active: Mock object for `save_active` interactions.
        mock_save_status: Mock object for `save_status` interactions.
    """
    mock_load_candidate.return_value = object()
    mock_load_status.return_value = OptimizerStatus(
        state="completed", candidate_ready=True, candidate_run_id="run-1"
    )

    run_promote(type("Args", (), {"run_id": "run-1", "workspace": "."})())

    assert mock_save_active.call_count == 1
    assert mock_save_status.call_count == 1
    status_arg = mock_save_status.call_args.args[1]
    assert status_arg.promoted is True
    assert status_arg.candidate_ready is False
    assert status_arg.candidate_run_id is None


@patch("crucis.__main__._is_optimizer_enabled_for_command", return_value=True)
@patch("crucis.__main__.save_active_policy")
@patch("crucis.__main__.load_candidate_policy")
@patch("crucis.__main__.load_optimizer_status")
def test_run_promote_requires_candidate_ready_metadata(
    mock_load_status,
    mock_load_candidate,
    mock_save_active,
    _mock_gate,
):
    """Promotion should fail when run is not candidate-ready.

    Args:
        mock_load_status: Mock object for `load_status` interactions.
        mock_load_candidate: Mock object for `load_candidate` interactions.
        mock_save_active: Mock object for `save_active` interactions.
    """
    mock_load_status.return_value = OptimizerStatus(
        state="completed",
        candidate_ready=False,
        candidate_run_id=None,
    )

    with pytest.raises(SystemExit):
        run_promote(type("Args", (), {"run_id": "run-1", "workspace": "."})())

    assert mock_load_candidate.call_count == 0
    assert mock_save_active.call_count == 0


@patch("crucis.__main__._is_optimizer_enabled_for_command", return_value=True)
@patch("crucis.__main__.save_active_policy")
@patch("crucis.__main__.load_candidate_policy")
@patch("crucis.__main__.load_optimizer_status")
def test_run_promote_requires_matching_candidate_run_id(
    mock_load_status,
    mock_load_candidate,
    mock_save_active,
    _mock_gate,
):
    """Promotion should fail when candidate-ready metadata points to another run.

    Args:
        mock_load_status: Mock object for `load_status` interactions.
        mock_load_candidate: Mock object for `load_candidate` interactions.
        mock_save_active: Mock object for `save_active` interactions.
    """
    mock_load_status.return_value = OptimizerStatus(
        state="completed",
        candidate_ready=True,
        candidate_run_id="run-2",
    )

    with pytest.raises(SystemExit):
        run_promote(type("Args", (), {"run_id": "run-1", "workspace": "."})())

    assert mock_load_candidate.call_count == 0
    assert mock_save_active.call_count == 0


@patch("crucis.__main__._is_optimizer_enabled_for_command", return_value=True)
@patch("crucis.__main__.save_optimizer_status")
@patch("crucis.__main__.save_active_policy")
@patch("crucis.__main__.load_candidate_policy")
@patch("crucis.__main__.load_optimizer_status", return_value=None)
def test_run_promote_force_overrides_candidate_ready_checks(
    _mock_load_status,
    mock_load_candidate,
    mock_save_active,
    mock_save_status,
    _mock_gate,
):
    """Force promotion should bypass candidate-ready guardrails.

    Args:
        _mock_load_status: Mock object for `load_status` interactions.
        mock_load_candidate: Mock object for `load_candidate` interactions.
        mock_save_active: Mock object for `save_active` interactions.
        mock_save_status: Mock object for `save_status` interactions.
    """
    mock_load_candidate.return_value = object()

    run_promote(type("Args", (), {"run_id": "run-1", "workspace": ".", "force": True})())

    assert mock_save_active.call_count == 1
    assert mock_save_status.call_count == 1


@patch("crucis.__main__._is_optimizer_enabled_for_command", return_value=True)
@patch("crucis.__main__.load_optimizer_status", return_value=None)
@patch("crucis.__main__.load_candidate_policy", side_effect=FileNotFoundError("missing"))
def test_run_promote_missing_candidate_exits(
    mock_load_candidate,
    _mock_load_status,
    _mock_gate,
):
    """Missing candidate run should surface error and exit non-zero.

    Args:
        mock_load_candidate: Mock object for `load_candidate` interactions.
        _mock_load_status: Mock object for `load_status` interactions.
    """
    with pytest.raises(SystemExit):
        run_promote(type("Args", (), {"run_id": "missing", "workspace": ".", "force": True})())
    assert mock_load_candidate.call_count == 1


@patch("crucis.__main__.run_doctor")
def test_run_doctor_command_json_output(mock_run_doctor, capsys):
    """doctor command should support machine-readable JSON output.

    Args:
        mock_run_doctor: Mock object for `run_doctor` interactions.
        capsys: Pytest capture fixture.
    """
    from crucis.diagnostics import DiagnosticCheck, DoctorReport

    mock_run_doctor.return_value = DoctorReport(
        ok=True,
        workspace=Path(".").resolve(),
        checks=[DiagnosticCheck(id="python_version", status="ok", message="ok")],
    )
    run_doctor_command(
        type(
            "Args",
            (),
            {
                "workspace": ".",
                "objective": None,
                "profiles": None,
                "checkpoint": None,
                "require_docker": False,
                "json": True,
            },
        )()
    )
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["ok"] is True
    assert isinstance(payload["checks"], list)


@patch("crucis.__main__._is_optimizer_enabled_for_command", return_value=True)
@patch("crucis.__main__.run_optimizer_worker")
def test_run_optimizer_worker_command_json_output(mock_run_worker, _mock_gate, capsys):
    """optimizer-worker command should expose JSON output with exit code.

    Args:
        mock_run_worker: Mock object for `run_optimizer_worker` interactions.
        capsys: Pytest capture fixture.
    """
    mock_run_worker.return_value = 0
    run_optimizer_worker_command(
        type("Args", (), {"workspace": ".", "loop": False, "json": True})()
    )
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["exit_code"] == 0
    assert payload["mode"] == "once"


# ---------------------------------------------------------------------------
# objective mutation command tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# init command handler tests
# ---------------------------------------------------------------------------


@patch("crucis.__main__.detect_existing_codebase", return_value=False)
@patch("crucis.__main__.scaffold_workspace")
def test_run_init_command_no_agent_scaffolds_workspace(
    mock_scaffold,
    _mock_detect,
    tmp_path,
    capsys,
):
    """Init with --no-agent should call scaffold_workspace and report files.

    Args:
        mock_scaffold: Mock object for scaffold_workspace.
        tmp_path: Temporary directory provided by pytest.
        capsys: Pytest capture fixture.
    """
    created = [tmp_path / "objective.yaml"]
    mock_scaffold.return_value = created

    args = type(
        "Args",
        (),
        {
            "workspace": str(tmp_path), "no_agent": True, "name": "foo",
            "existing_codebase": False, "with_profiles": False, "with_settings": False,
        },
    )()
    run_init_command(args)

    mock_scaffold.assert_called_once_with(
        tmp_path.resolve(), name="foo", existing_codebase=False, agent=None, model=None,
        include_profiles=False, include_settings=False,
    )
    output = capsys.readouterr().err
    assert "objective.yaml" in output


@patch("crucis.__main__.scaffold_workspace", return_value=[])
def test_run_init_command_already_initialized(_mock_scaffold, tmp_path, capsys):
    """Init should report already initialized when scaffold returns no files.

    Args:
        _mock_scaffold: Mock for scaffold_workspace returning empty list.
        tmp_path: Temporary directory provided by pytest.
        capsys: Pytest capture fixture.
    """
    args = type(
        "Args",
        (),
        {"workspace": str(tmp_path), "no_agent": True, "name": "x", "existing_codebase": False},
    )()
    run_init_command(args)

    output = capsys.readouterr().err
    assert "already initialized" in output


@patch("crucis.__main__.detect_existing_codebase", return_value=False)
@patch("crucis.__main__.scaffold_workspace")
@patch("crucis.__main__._try_agent_onboarding", return_value=False)
def test_run_init_command_agent_fallback(mock_try_agent, mock_scaffold, _mock_detect, tmp_path):
    """Init should fall back to static scaffolding when agent onboarding fails.

    Args:
        mock_try_agent: Mock for agent onboarding returning False.
        mock_scaffold: Mock object for scaffold_workspace.
        tmp_path: Temporary directory provided by pytest.
    """
    mock_scaffold.return_value = [tmp_path / "objective.yaml"]
    args = type(
        "Args",
        (),
        {"workspace": str(tmp_path), "no_agent": False, "name": "p", "existing_codebase": False},
    )()
    run_init_command(args)

    mock_try_agent.assert_called_once()
    mock_scaffold.assert_called_once()


@patch("crucis.__main__.scaffold_workspace")
def test_run_init_command_rejects_no_agent_with_require_agent(mock_scaffold, tmp_path):
    """Init should reject mutually exclusive --no-agent and --require-agent."""
    args = type(
        "Args",
        (),
        {
            "workspace": str(tmp_path),
            "no_agent": True,
            "require_agent": True,
            "name": "p",
            "agent": None,
            "existing_codebase": False,
        },
    )()

    with pytest.raises(SystemExit) as exc:
        run_init_command(args)

    assert exc.value.code == 2
    assert mock_scaffold.call_count == 0


@patch("crucis.__main__.scaffold_workspace")
@patch("crucis.__main__._is_interactive_terminal", return_value=False)
def test_run_init_command_non_interactive_falls_back_to_static(
    _mock_tty,
    mock_scaffold,
    tmp_path,
):
    """Init should skip onboarding and scaffold templates in non-interactive shells."""
    mock_scaffold.return_value = [tmp_path / "objective.yaml"]
    args = type(
        "Args",
        (),
        {
            "workspace": str(tmp_path),
            "no_agent": False,
            "require_agent": False,
            "name": "p",
            "agent": "claude",
            "existing_codebase": False,
        },
    )()

    run_init_command(args)

    assert mock_scaffold.call_count == 1


@patch("crucis.__main__.scaffold_workspace")
@patch("crucis.__main__._is_interactive_terminal", return_value=False)
def test_run_init_command_require_agent_exits_in_non_interactive_shell(
    _mock_tty,
    mock_scaffold,
    tmp_path,
):
    """Init with --require-agent should fail in non-interactive shells."""
    args = type(
        "Args",
        (),
        {
            "workspace": str(tmp_path),
            "no_agent": False,
            "require_agent": True,
            "name": "p",
            "agent": "claude",
            "existing_codebase": False,
        },
    )()

    with pytest.raises(SystemExit) as exc:
        run_init_command(args)

    assert exc.value.code == 1
    assert mock_scaffold.call_count == 0


@patch("crucis.__main__.scaffold_workspace")
@patch("crucis.__main__._is_interactive_terminal", return_value=True)
@patch("shutil.which", return_value=None)
def test_run_init_command_require_agent_exits_when_agent_missing(
    _mock_which,
    _mock_tty,
    mock_scaffold,
    tmp_path,
):
    """Init with --require-agent should fail when agent binary is missing."""
    args = type(
        "Args",
        (),
        {
            "workspace": str(tmp_path),
            "no_agent": False,
            "require_agent": True,
            "name": "p",
            "agent": "claude",
            "existing_codebase": False,
        },
    )()

    with pytest.raises(SystemExit) as exc:
        run_init_command(args)

    assert exc.value.code == 1
    assert mock_scaffold.call_count == 0


@patch("crucis.__main__.detect_existing_codebase", return_value=True)
@patch("crucis.__main__.scaffold_workspace")
def test_run_init_command_existing_codebase_auto_mode(
    mock_scaffold,
    _mock_detect,
    tmp_path,
    capsys,
):
    """Init should auto-switch scaffold mode when existing Python files are detected."""
    mock_scaffold.return_value = [tmp_path / "objective.yaml"]
    args = type(
        "Args",
        (),
        {
            "workspace": str(tmp_path), "no_agent": True, "name": "p",
            "existing_codebase": False, "with_profiles": False, "with_settings": False,
        },
    )()

    run_init_command(args)

    mock_scaffold.assert_called_once_with(
        tmp_path.resolve(), name="p", existing_codebase=True, agent=None, model=None,
        include_profiles=False, include_settings=False,
    )
    output = capsys.readouterr().err
    assert "Existing codebase detected" in output


@patch("crucis.__main__.detect_existing_codebase", return_value=False)
@patch("crucis.__main__.scaffold_workspace")
def test_run_init_command_existing_codebase_flag_forces_mode(
    mock_scaffold,
    _mock_detect,
    tmp_path,
):
    """--existing-codebase should force existing-repo scaffold behavior."""
    mock_scaffold.return_value = [tmp_path / "objective.yaml"]
    args = type(
        "Args",
        (),
        {
            "workspace": str(tmp_path), "no_agent": True, "name": "p",
            "existing_codebase": True, "with_profiles": False, "with_settings": False,
        },
    )()

    run_init_command(args)

    mock_scaffold.assert_called_once_with(
        tmp_path.resolve(), name="p", existing_codebase=True, agent=None, model=None,
        include_profiles=False, include_settings=False,
    )


@patch("crucis.__main__.scaffold_workspace")
@patch("crucis.__main__.detect_existing_codebase", return_value=False)
def test_run_init_command_warns_on_unsupported_python(
    mock_detect,
    mock_scaffold,
    tmp_path,
    capsys,
):
    """Init should emit a clear warning on unsupported Python versions."""
    mock_scaffold.return_value = [tmp_path / "objective.yaml"]
    args = type(
        "Args",
        (),
        {"workspace": str(tmp_path), "no_agent": True, "name": "p", "existing_codebase": False},
    )()

    with patch(
        "crucis.__main__.sys.version_info",
        SimpleNamespace(major=3, minor=11, micro=9),
    ):
        run_init_command(args)

    assert mock_detect.call_count == 1
    assert mock_scaffold.call_count == 1
    output = capsys.readouterr().err
    assert "supported but Python 3.12+ is recommended" in output


# ---------------------------------------------------------------------------
# run --plan handler tests
# ---------------------------------------------------------------------------


def test_run_plan_missing_objective_exits(tmp_path):
    """run --plan should exit 1 when objective file does not exist.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    from crucis.__main__ import _handle_run_plan

    args = type(
        "Args",
        (),
        {
            "objective_path": str(tmp_path / "missing.yaml"),
            "objective_flag": None,
            "profiles": "constraints/profiles.yaml",
            "workspace": str(tmp_path),
            "force_plan": False,
        },
    )()
    with pytest.raises(SystemExit) as exc:
        _handle_run_plan(args)
    assert exc.value.code == 1


def test_run_plan_existing_plan_without_force_exits(tmp_path):
    """run --plan should exit 1 when plan.md exists and --force-plan is not set.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    from crucis.__main__ import _handle_run_plan

    objective = tmp_path / "objective.yaml"
    objective.write_text("name: add\ndescription: Add", encoding="utf-8")
    (tmp_path / "plan.md").write_text("existing plan", encoding="utf-8")

    args = type(
        "Args",
        (),
        {
            "objective_path": str(objective),
            "objective_flag": None,
            "profiles": "constraints/profiles.yaml",
            "workspace": str(tmp_path),
            "force_plan": False,
        },
    )()
    with pytest.raises(SystemExit) as exc:
        _handle_run_plan(args)
    assert exc.value.code == 1


@patch("crucis.__main__.write_plan_to_workspace")
@patch("crucis.__main__.build_generation_plan", return_value="# Plan content")
@patch("crucis.__main__.load_profiles", return_value={"recommended": {"primary": {}}})
@patch("crucis.__main__.resolve_constraints")
@patch("crucis.__main__.parse_objective")
@patch("crucis.__main__._ensure_runtime_settings")
def test_run_plan_calls_build_generation_plan(
    _mock_settings,
    mock_parse,
    mock_resolve,
    mock_load_profiles,
    mock_build_plan,
    mock_write_plan,
    tmp_path,
):
    """run --plan should parse objective, resolve constraints, and write plan file.

    Args:
        _mock_settings: Mock for runtime settings validation.
        mock_parse: Mock object for parse_objective.
        mock_resolve: Mock object for resolve_constraints.
        mock_load_profiles: Mock object for load_profiles.
        mock_build_plan: Mock object for build_generation_plan.
        mock_write_plan: Mock object for write_plan_to_workspace.
        tmp_path: Temporary directory provided by pytest.
    """
    from crucis.__main__ import _handle_run_plan
    from crucis.models import ParsedObjective, TaskObjective

    objective = tmp_path / "objective.yaml"
    objective.write_text("name: add\ndescription: Add", encoding="utf-8")
    profiles = tmp_path / "constraints" / "profiles.yaml"
    profiles.parent.mkdir()
    profiles.write_text("profiles: {}", encoding="utf-8")

    task = TaskObjective(name="add", description="Add numbers")
    mock_parse.return_value = ParsedObjective(
        name="add", description="Add numbers", tasks=[task]
    )
    mock_write_plan.return_value = tmp_path / "plan.md"

    args = type(
        "Args",
        (),
        {
            "objective_path": str(objective),
            "objective_flag": None,
            "profiles": str(profiles),
            "workspace": str(tmp_path),
            "force_plan": False,
        },
    )()
    _handle_run_plan(args)

    mock_build_plan.assert_called_once()
    mock_write_plan.assert_called_once()


@patch("crucis.__main__.write_plan_to_workspace")
@patch("crucis.__main__.build_generation_plan", return_value="# Plan content")
@patch("crucis.__main__.load_profiles", return_value={"recommended": {"primary": {}}})
@patch("crucis.__main__.resolve_constraints")
@patch("crucis.__main__.parse_objective")
@patch("crucis.__main__._ensure_runtime_settings")
def test_run_plan_single_objective_resolves_constraints_for_objective_name(
    _mock_settings,
    mock_parse,
    mock_resolve,
    _mock_load_profiles,
    mock_build_plan,
    _mock_write_plan,
    tmp_path,
):
    """run --plan should build constraint map from objective name when tasks are omitted."""
    from crucis.__main__ import _handle_run_plan
    from crucis.models import ParsedObjective

    objective = tmp_path / "objective.yaml"
    objective.write_text("name: add\ndescription: Add", encoding="utf-8")
    profiles = tmp_path / "constraints" / "profiles.yaml"
    profiles.parent.mkdir()
    profiles.write_text("profiles: {}", encoding="utf-8")

    mock_parse.return_value = ParsedObjective(name="add", description="Add numbers")
    mock_resolve.return_value = {"primary": {}}  # type: ignore[assignment]

    args = type(
        "Args",
        (),
        {
            "objective_path": str(objective),
            "objective_flag": None,
            "profiles": str(profiles),
            "workspace": str(tmp_path),
            "force_plan": False,
        },
    )()
    _handle_run_plan(args)

    assert mock_resolve.call_count == 1
    assert mock_resolve.call_args.args[2] == "add"
    constraints_map = mock_build_plan.call_args.args[1]
    assert list(constraints_map.keys()) == ["add"]
