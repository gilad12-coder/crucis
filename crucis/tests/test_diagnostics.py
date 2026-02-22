"""Tests for diagnostics and preflight checks."""

from pathlib import Path

from crucis.config import Config
from crucis.diagnostics import collect_preflight_checks, doctor_report_payload, run_doctor


def _mock_tools_available(monkeypatch) -> None:
    """Make doctor checks deterministic in tests.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
    """
    from crucis.diagnostics import DiagnosticCheck

    monkeypatch.setattr(
        "crucis.diagnostics._check_python_version",
        lambda: DiagnosticCheck(id="python_version", status="ok", message="python ok"),
    )
    monkeypatch.setattr("crucis.diagnostics.shutil.which", lambda _binary: "/usr/bin/fake")
    monkeypatch.setattr("crucis.diagnostics.importlib.util.find_spec", lambda _name: object())
    monkeypatch.setattr("crucis.diagnostics.check_docker_available", lambda: True)


def test_git_repository_check_warns_when_no_git(tmp_path: Path) -> None:
    """Git check should warn when workspace is not inside a git repository.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    from crucis.diagnostics import _check_git_repository

    result = _check_git_repository(tmp_path)
    assert result.id == "git_repository"
    assert result.status == "warn"


def test_git_repository_check_ok_when_git_exists(tmp_path: Path) -> None:
    """Git check should pass when .git directory exists.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    from crucis.diagnostics import _check_git_repository

    (tmp_path / ".git").mkdir()
    result = _check_git_repository(tmp_path)
    assert result.id == "git_repository"
    assert result.status == "ok"


def test_collect_preflight_checks_reports_missing_agent_binary(
    tmp_path: Path, monkeypatch
) -> None:
    """Preflight should report a clear failure when a required binary is absent.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture.
    """
    monkeypatch.setattr("crucis.diagnostics.shutil.which", lambda _binary: None)
    monkeypatch.setattr("crucis.diagnostics.check_docker_available", lambda: True)

    checks = collect_preflight_checks(
        workspace=tmp_path,
        config=Config(),
        required_agents={"missing-agent"},
        require_pytest=False,
    )
    failed = [check for check in checks if check.status == "fail"]
    assert any(check.id == "agent_missing-agent" for check in failed)


def test_run_doctor_ok_with_valid_workspace_artifacts(tmp_path: Path, monkeypatch) -> None:
    """Doctor should pass when required binaries/modules and files are valid.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture.
    """
    _mock_tools_available(monkeypatch)
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
    profiles_dir = tmp_path / "constraints"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    profiles_path = profiles_dir / "profiles.yaml"
    profiles_path.write_text("profiles:\n  default: {}\n", encoding="utf-8")
    checkpoint_path = tmp_path / ".checkpoint.json"
    checkpoint_path.write_text(
        '{"task_progress": [{"name": "add", "status": "complete"}]}',
        encoding="utf-8",
    )

    report = run_doctor(
        workspace=tmp_path,
        objective_path=objective_path,
        profiles_path=profiles_path,
        checkpoint_path=checkpoint_path,
    )
    assert report.ok is True
    payload = doctor_report_payload(report)
    assert payload["ok"] is True
    assert payload["workspace"] == str(tmp_path.resolve())
    assert isinstance(payload["checks"], list)


def test_run_doctor_fails_when_checkpoint_missing(tmp_path: Path, monkeypatch) -> None:
    """Doctor should fail when an explicitly requested checkpoint does not exist.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture.
    """
    _mock_tools_available(monkeypatch)
    report = run_doctor(
        workspace=tmp_path,
        checkpoint_path=Path(".checkpoint.json"),
    )
    assert report.ok is False
    failed = [check for check in report.checks if check.status == "fail"]
    assert any(check.id == "checkpoint" for check in failed)
