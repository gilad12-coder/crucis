"""Tests for Crucis CLI entrypoint."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from crucis.__main__ import (
    build_parser,
    main,
    run_add_eval_command,
    run_add_task_command,
    run_doctor_command,
    run_evaluate,
    run_init_command,
    run_optimizer_worker_command,
    run_plan_command,
    run_promote,
    show_checkpoint,
)
from crucis.models import CheckpointState, TaskProgress, TrainingStatus
from crucis.persistence.policy import OptimizerStatus


class TestBuildParser:
    """Parser shape tests for new strict command set."""

    def test_fit_subcommand(self):
        """Test fit subcommand."""
        parser = build_parser()
        args = parser.parse_args(["fit", "objective.yaml"])
        assert args.command == "fit"
        assert args.objective_path == "objective.yaml"

    def test_checkpoint_subcommand(self):
        """Test checkpoint subcommand."""
        parser = build_parser()
        args = parser.parse_args(["checkpoint"])
        assert args.command == "checkpoint"
        assert args.checkpoint == ".checkpoint.json"
        assert args.json is False

    def test_evaluate_subcommand(self):
        """Test evaluate subcommand."""
        parser = build_parser()
        args = parser.parse_args(["evaluate", "--objective", "obj.yaml"])
        assert args.command == "evaluate"
        assert args.objective == "obj.yaml"

    def test_migrate_subcommand(self):
        """Test migrate subcommand."""
        parser = build_parser()
        args = parser.parse_args(
            ["migrate", "--objective-in", "old.yaml", "--objective-out", "new.yaml"]
        )
        assert args.command == "migrate"

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
        assert args.agent is None

    def test_init_subcommand_with_flags(self):
        """Test init subcommand with explicit flags."""
        parser = build_parser()
        args = parser.parse_args(
            ["init", "--name", "foo", "--workspace", "/tmp", "--no-agent", "--require-agent"]
        )
        assert args.name == "foo"
        assert args.workspace == "/tmp"
        assert args.no_agent is True
        assert args.require_agent is True

    def test_plan_subcommand(self):
        """Test plan subcommand defaults."""
        parser = build_parser()
        args = parser.parse_args(["plan", "objective.yaml"])
        assert args.command == "plan"
        assert args.objective_path == "objective.yaml"
        assert args.profiles == "constraints/profiles.yaml"
        assert args.force is False

    def test_plan_subcommand_force(self):
        """Test plan subcommand force flag."""
        parser = build_parser()
        args = parser.parse_args(["plan", "objective.yaml", "--force"])
        assert args.force is True

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
    def test_main_fit_calls_run_fit(self, mock_run_fit, _mock_preflight, tmp_path):
        """Test main fit calls run fit.

        Args:
            mock_run_fit: Mock object for `run_fit` interactions.
            tmp_path: Temporary directory provided by pytest.
        """
        objective = tmp_path / "objective.yaml"
        objective.write_text("name: add\ndescription: Add", encoding="utf-8")
        main(["fit", str(objective), "--checkpoint", "cp.json"])
        mock_run_fit.assert_called_once_with(
            objective_path=objective,
            profiles_path=Path("constraints/profiles.yaml"),
            checkpoint_path=Path("cp.json"),
            auto_tests=False,
            auto_adversary=False,
            auto_evaluate=False,
            workspace=None,
        )

    @patch("crucis.__main__.load_runtime_settings", side_effect=ValueError("invalid settings"))
    @patch("crucis.__main__.run_fit")
    def test_main_fit_exits_when_runtime_settings_invalid(
        self,
        mock_run_fit,
        _mock_load_settings,
        tmp_path,
    ):
        """Fit should fail fast when runtime settings cannot be loaded.

        Args:
            mock_run_fit: Mock object for `run_fit` interactions.
            _mock_load_settings: Unused mock for `load_runtime_settings`.
            tmp_path: Temporary directory provided by pytest.
        """
        objective = tmp_path / "objective.yaml"
        objective.write_text("name: add\ndescription: Add", encoding="utf-8")

        with pytest.raises(SystemExit) as exc:
            main(["fit", str(objective)])

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

        monkeypatch.setattr(sys, "argv", ["crucis", "fit", str(objective)])
        main()

        mock_run_fit.assert_called_once()

    @patch("crucis.__main__._run_preflight_or_exit")
    @patch("crucis.__main__.run_evaluate")
    def test_main_evaluate_calls_run_evaluate(self, mock_eval, _mock_preflight):
        """Test main evaluate calls run evaluate.

        Args:
            mock_eval: Mock object for `eval` interactions.
        """
        main(["evaluate", "--objective", "obj.yaml", "--no-sandbox"])
        mock_eval.assert_called_once_with(
            objective_path=Path("obj.yaml"),
            profiles_path=Path("constraints/profiles.yaml"),
            checkpoint_path=Path(".checkpoint.json"),
            use_sandbox=False,
            workspace=None,
        )

    @patch("crucis.__main__.show_checkpoint")
    def test_main_checkpoint_calls_show(self, mock_show):
        """Test main checkpoint calls show.

        Args:
            mock_show: Mock object for `show` interactions.
        """
        main(["checkpoint", "--checkpoint", "cp.json"])
        mock_show.assert_called_once_with(Path("cp.json"), as_json=False)

    @patch("crucis.__main__.show_checkpoint")
    def test_main_checkpoint_json_calls_show(self, mock_show):
        """Test main checkpoint --json calls show with JSON mode.

        Args:
            mock_show: Mock object for `show` interactions.
        """
        main(["checkpoint", "--checkpoint", "cp.json", "--json"])
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

    @patch("crucis.__main__.migrate_objective_file")
    @patch("crucis.__main__.migrate_checkpoint_file")
    def test_main_migrate_calls_tools(self, mock_migrate_cp, mock_migrate_obj):
        """Test main migrate calls tools.

        Args:
            mock_migrate_cp: Mock object for `migrate_cp` interactions.
            mock_migrate_obj: Mock object for `migrate_obj` interactions.
        """
        main(
            [
                "migrate",
                "--objective-in",
                "old.yaml",
                "--objective-out",
                "new.yaml",
                "--checkpoint-in",
                "old.json",
                "--checkpoint-out",
                "new.json",
            ]
        )
        mock_migrate_obj.assert_called_once_with(Path("old.yaml"), Path("new.yaml"))
        mock_migrate_cp.assert_called_once_with(Path("old.json"), Path("new.json"))

    def test_main_migrate_malformed_yaml_prints_clean_error(self, tmp_path, capsys):
        """migrate should report parse errors without a traceback."""
        objective_in = tmp_path / "bad.yaml"
        objective_out = tmp_path / "objective.yaml"
        objective_in.write_text("name: [invalid: yaml: {{", encoding="utf-8")

        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "migrate",
                    "--objective-in",
                    str(objective_in),
                    "--objective-out",
                    str(objective_out),
                ]
            )

        assert exc.value.code == 1
        output = capsys.readouterr().out
        assert "Could not parse YAML" in output
        assert "Traceback" not in output

    @patch("crucis.__main__.run_init_command")
    def test_main_init_calls_run_init_command(self, mock_init):
        """Init command should dispatch to init handler.

        Args:
            mock_init: Mock object for init command handler.
        """
        main(["init"])
        assert mock_init.call_count == 1

    @patch("crucis.__main__.run_plan_command")
    def test_main_plan_calls_run_plan_command(self, mock_plan, tmp_path):
        """Plan command should dispatch to plan handler.

        Args:
            mock_plan: Mock object for plan command handler.
            tmp_path: Temporary directory provided by pytest.
        """
        objective = tmp_path / "objective.yaml"
        objective.write_text("name: add\ndescription: Add", encoding="utf-8")
        main(["plan", str(objective)])
        assert mock_plan.call_count == 1

    @patch("crucis.__main__.run_promote")
    def test_main_promote_calls_run_promote(self, mock_promote):
        """Test main promote calls run promote.

        Args:
            mock_promote: Mock object for `promote` interactions.
        """
        main(["promote", "--run-id", "run-1"])
        mock_promote.assert_called_once()

    def test_legacy_command_fails_fast(self):
        """Test legacy command fails fast."""
        with pytest.raises(SystemExit):
            main(["run", "spec.yaml"])

    def test_legacy_flag_fails_fast(self, tmp_path):
        """Test legacy flag fails fast.

        Args:
            tmp_path: Temporary directory provided by pytest.
        """
        objective = tmp_path / "objective.yaml"
        objective.write_text("name: add\ndescription: Add", encoding="utf-8")
        with pytest.raises(SystemExit):
            main(["fit", str(objective), "--session", "x.json"])

    def test_legacy_preview_command_shows_replacement_hint(self, capsys):
        """Legacy preview command should redirect users to fit --dry-run."""
        with pytest.raises(SystemExit) as exc:
            main(["preview", "objective.yaml"])
        assert exc.value.code == 2
        output = capsys.readouterr().out
        assert "crucis fit <objective.yaml>" in output
        assert "--dry-run" in output


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
@patch("crucis.__main__.load_optimizer_status")
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


@patch("crucis.__main__.load_optimizer_status", return_value=OptimizerStatus(state="idle"))
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


@patch("crucis.__main__.save_optimizer_status")
@patch("crucis.__main__.save_active_policy")
@patch("crucis.__main__.load_optimizer_status")
@patch("crucis.__main__.load_candidate_policy")
def test_run_promote_promotes_candidate_policy(
    mock_load_candidate,
    mock_load_status,
    mock_save_active,
    mock_save_status,
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


@patch("crucis.__main__.save_active_policy")
@patch("crucis.__main__.load_candidate_policy")
@patch("crucis.__main__.load_optimizer_status")
def test_run_promote_requires_candidate_ready_metadata(
    mock_load_status,
    mock_load_candidate,
    mock_save_active,
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


@patch("crucis.__main__.save_active_policy")
@patch("crucis.__main__.load_candidate_policy")
@patch("crucis.__main__.load_optimizer_status")
def test_run_promote_requires_matching_candidate_run_id(
    mock_load_status,
    mock_load_candidate,
    mock_save_active,
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


@patch("crucis.__main__.save_optimizer_status")
@patch("crucis.__main__.save_active_policy")
@patch("crucis.__main__.load_candidate_policy")
@patch("crucis.__main__.load_optimizer_status", return_value=None)
def test_run_promote_force_overrides_candidate_ready_checks(
    _mock_load_status,
    mock_load_candidate,
    mock_save_active,
    mock_save_status,
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


@patch("crucis.__main__.load_optimizer_status", return_value=None)
@patch("crucis.__main__.load_candidate_policy", side_effect=FileNotFoundError("missing"))
def test_run_promote_missing_candidate_exits(
    mock_load_candidate,
    _mock_load_status,
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


@patch("crucis.__main__.run_optimizer_worker")
def test_run_optimizer_worker_command_json_output(mock_run_worker, capsys):
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


def test_run_add_task_invalid_name_rolls_back_file(tmp_path):
    """add-task should not modify objective file when validation fails."""
    objective = tmp_path / "objective.yaml"
    original = "name: add\ndescription: Add numbers\ntrain_evals:\n  - input: \"(1, 2)\"\n    output: \"3\"\n"
    objective.write_text(original, encoding="utf-8")

    args = type(
        "Args",
        (),
        {
            "objective_path": str(objective),
            "name": "bad-name",
            "description": None,
            "signature": None,
        },
    )()

    with pytest.raises(SystemExit) as exc:
        run_add_task_command(args)

    assert exc.value.code == 1
    assert objective.read_text(encoding="utf-8") == original


@patch("crucis.__main__.parse_objective", side_effect=ValueError("synthetic validation failure"))
def test_run_add_eval_validation_failure_rolls_back_file(_mock_parse, tmp_path):
    """add-eval should not modify objective file when post-write validation fails."""
    objective = tmp_path / "objective.yaml"
    original = (
        "name: add\n"
        "description: Add numbers\n"
        "train_evals:\n"
        "  - input: \"(1, 2)\"\n"
        "    output: \"3\"\n"
    )
    objective.write_text(original, encoding="utf-8")

    args = type(
        "Args",
        (),
        {
            "objective_path": str(objective),
            "task": None,
            "eval_input": "(2, 3)",
            "eval_output": "5",
        },
    )()

    with pytest.raises(SystemExit) as exc:
        run_add_eval_command(args)

    assert exc.value.code == 1
    assert objective.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# init command handler tests
# ---------------------------------------------------------------------------


@patch("crucis.__main__.scaffold_workspace")
def test_run_init_command_no_agent_scaffolds_workspace(mock_scaffold, tmp_path, capsys):
    """Init with --no-agent should call scaffold_workspace and report files.

    Args:
        mock_scaffold: Mock object for scaffold_workspace.
        tmp_path: Temporary directory provided by pytest.
        capsys: Pytest capture fixture.
    """
    created = [tmp_path / "objective.yaml", tmp_path / ".crucis" / "settings.yaml"]
    mock_scaffold.return_value = created

    args = type("Args", (), {"workspace": str(tmp_path), "no_agent": True, "name": "foo"})()
    run_init_command(args)

    mock_scaffold.assert_called_once_with(tmp_path.resolve(), name="foo")
    output = capsys.readouterr().out
    assert "objective.yaml" in output


@patch("crucis.__main__.scaffold_workspace", return_value=[])
def test_run_init_command_already_initialized(_mock_scaffold, tmp_path, capsys):
    """Init should report already initialized when scaffold returns no files.

    Args:
        _mock_scaffold: Mock for scaffold_workspace returning empty list.
        tmp_path: Temporary directory provided by pytest.
        capsys: Pytest capture fixture.
    """
    args = type("Args", (), {"workspace": str(tmp_path), "no_agent": True, "name": "x"})()
    run_init_command(args)

    output = capsys.readouterr().out
    assert "already initialized" in output


@patch("crucis.__main__.scaffold_workspace")
@patch("crucis.__main__._try_agent_onboarding", return_value=False)
def test_run_init_command_agent_fallback(mock_try_agent, mock_scaffold, tmp_path):
    """Init should fall back to static scaffolding when agent onboarding fails.

    Args:
        mock_try_agent: Mock for agent onboarding returning False.
        mock_scaffold: Mock object for scaffold_workspace.
        tmp_path: Temporary directory provided by pytest.
    """
    mock_scaffold.return_value = [tmp_path / "objective.yaml"]
    args = type("Args", (), {"workspace": str(tmp_path), "no_agent": False, "name": "p"})()
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
        },
    )()

    with pytest.raises(SystemExit) as exc:
        run_init_command(args)

    assert exc.value.code == 1
    assert mock_scaffold.call_count == 0


# ---------------------------------------------------------------------------
# plan command handler tests
# ---------------------------------------------------------------------------


def test_run_plan_command_missing_objective_exits(tmp_path):
    """Plan should exit 1 when objective file does not exist.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    args = type(
        "Args",
        (),
        {
            "objective_path": str(tmp_path / "missing.yaml"),
            "profiles": "constraints/profiles.yaml",
            "workspace": str(tmp_path),
            "force": False,
        },
    )()
    with pytest.raises(SystemExit) as exc:
        run_plan_command(args)
    assert exc.value.code == 1


def test_run_plan_command_existing_plan_without_force_exits(tmp_path):
    """Plan should exit 1 when plan.md exists and --force is not set.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective = tmp_path / "objective.yaml"
    objective.write_text("name: add\ndescription: Add", encoding="utf-8")
    (tmp_path / "plan.md").write_text("existing plan", encoding="utf-8")

    args = type(
        "Args",
        (),
        {
            "objective_path": str(objective),
            "profiles": "constraints/profiles.yaml",
            "workspace": str(tmp_path),
            "force": False,
        },
    )()
    with pytest.raises(SystemExit) as exc:
        run_plan_command(args)
    assert exc.value.code == 1


@patch("crucis.__main__.write_plan_to_workspace")
@patch("crucis.__main__.build_generation_plan", return_value="# Plan content")
@patch("crucis.__main__.load_profiles", return_value={"recommended": {"primary": {}}})
@patch("crucis.__main__.resolve_constraints")
@patch("crucis.__main__.parse_objective")
@patch("crucis.__main__._ensure_runtime_settings")
def test_run_plan_command_calls_build_generation_plan(
    _mock_settings,
    mock_parse,
    mock_resolve,
    mock_load_profiles,
    mock_build_plan,
    mock_write_plan,
    tmp_path,
):
    """Plan should parse objective, resolve constraints, and write plan file.

    Args:
        _mock_settings: Mock for runtime settings validation.
        mock_parse: Mock object for parse_objective.
        mock_resolve: Mock object for resolve_constraints.
        mock_load_profiles: Mock object for load_profiles.
        mock_build_plan: Mock object for build_generation_plan.
        mock_write_plan: Mock object for write_plan_to_workspace.
        tmp_path: Temporary directory provided by pytest.
    """
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
            "profiles": str(profiles),
            "workspace": str(tmp_path),
            "force": False,
        },
    )()
    run_plan_command(args)

    mock_build_plan.assert_called_once()
    mock_write_plan.assert_called_once()


@patch("crucis.__main__.write_plan_to_workspace")
@patch("crucis.__main__.build_generation_plan", return_value="# Plan content")
@patch("crucis.__main__.load_profiles", return_value={"recommended": {"primary": {}}})
@patch("crucis.__main__.resolve_constraints")
@patch("crucis.__main__.parse_objective")
@patch("crucis.__main__._ensure_runtime_settings")
def test_run_plan_command_single_objective_resolves_constraints_for_objective_name(
    _mock_settings,
    mock_parse,
    mock_resolve,
    _mock_load_profiles,
    mock_build_plan,
    _mock_write_plan,
    tmp_path,
):
    """Plan should build constraint map from objective name when tasks are omitted."""
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
            "profiles": str(profiles),
            "workspace": str(tmp_path),
            "force": False,
        },
    )()
    run_plan_command(args)

    assert mock_resolve.call_count == 1
    assert mock_resolve.call_args.args[2] == "add"
    constraints_map = mock_build_plan.call_args.args[1]
    assert list(constraints_map.keys()) == ["add"]
