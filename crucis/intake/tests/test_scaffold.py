"""Tests for onboarding scaffolding helpers."""

from unittest.mock import patch

from crucis.intake.scaffold import run_agent_onboarding


@patch("crucis.intake.scaffold.build_onboarding_prompt", return_value="PROMPT")
@patch("crucis.cli.runner.run_interactive_agent", return_value=1)
def test_run_agent_onboarding_codex_restores_existing_agents_md(
    mock_run_interactive,
    _mock_prompt,
    tmp_path,
):
    """Codex onboarding should restore pre-existing AGENTS.md after the run."""
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("existing instructions", encoding="utf-8")

    success = run_agent_onboarding(tmp_path, "codex", "model")

    assert success is False
    assert agents_md.read_text(encoding="utf-8") == "existing instructions"
    assert not (tmp_path / "AGENTS.md.crucis-backup").exists()
    assert mock_run_interactive.call_count == 1


@patch("crucis.intake.scaffold.build_onboarding_prompt", return_value="PROMPT")
@patch("crucis.cli.runner.run_interactive_agent", return_value=1)
def test_run_agent_onboarding_claude_preserves_existing_agents_md(
    mock_run_interactive,
    _mock_prompt,
    tmp_path,
):
    """Non-codex onboarding should leave AGENTS.md untouched."""
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("existing instructions", encoding="utf-8")

    success = run_agent_onboarding(tmp_path, "claude", "model")

    assert success is False
    assert agents_md.read_text(encoding="utf-8") == "existing instructions"
    assert not (tmp_path / "AGENTS.md.crucis-backup").exists()
    assert mock_run_interactive.call_count == 1
