"""Tests for onboarding scaffolding helpers."""

from unittest.mock import patch

import yaml

from crucis.intake.scaffold import (
    _render_settings_template,
    detect_existing_codebase,
    prompt_model_selection,
    run_agent_onboarding,
    scaffold_workspace,
)


@patch("crucis.intake.scaffold.build_onboarding_prompt", return_value="PROMPT")
@patch("crucis.cli.runner.run_interactive_agent", return_value=(1, ""))
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
@patch("crucis.cli.runner.run_interactive_agent", return_value=(1, ""))
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


def test_detect_existing_codebase_finds_python_sources(tmp_path):
    """Existing-codebase detection should trigger when Python files already exist."""
    (tmp_path / "pkg").mkdir(parents=True)
    (tmp_path / "pkg" / "module.py").write_text(
        "def ping():\n    return 'pong'\n",
        encoding="utf-8",
    )

    assert detect_existing_codebase(tmp_path) is True


def test_scaffold_workspace_existing_codebase_skips_solution_placeholder(tmp_path):
    """Existing-codebase mode should avoid creating src/solution.py."""
    (tmp_path / "crucis_pkg").mkdir(parents=True)
    (tmp_path / "crucis_pkg" / "existing.py").write_text("VALUE = 1\n", encoding="utf-8")

    created = scaffold_workspace(tmp_path, name="demo")

    assert (tmp_path / "src" / "solution.py").exists() is False
    assert tmp_path / "objective.yaml" in created
    objective = yaml.safe_load((tmp_path / "objective.yaml").read_text(encoding="utf-8"))
    assert objective["target_files"] == []
    assert "tasks" not in objective
    assert objective["context_files"] == []
    assert objective["existing_tests"] == []


def test_scaffold_workspace_new_project_creates_solution_placeholder(tmp_path):
    """Starter-project mode should continue creating src/solution.py."""
    created = scaffold_workspace(tmp_path, name="demo", existing_codebase=False)

    assert tmp_path / "src" / "solution.py" in created
    assert (tmp_path / "src" / "solution.py").exists() is True


def test_prompt_model_selection_non_interactive():
    """Non-interactive terminal should return (None, None)."""
    with patch("crucis.intake.scaffold.sys") as mock_sys:
        mock_sys.stdin.isatty.return_value = False
        result = prompt_model_selection()
    assert result == (None, None)


def test_prompt_model_selection_picks_claude_sonnet():
    """Interactive selection of claude + sonnet should return correct tuple."""
    with patch("crucis.intake.scaffold.sys") as mock_sys, \
         patch("crucis.display.prompt_input", side_effect=["1", "2"]), \
         patch("builtins.print"):
        mock_sys.stdin.isatty.return_value = True
        agent, model = prompt_model_selection()
    assert agent == "claude"
    assert model == "claude-sonnet-4-6"


def test_prompt_model_selection_defaults_on_empty():
    """Pressing enter without input should select defaults (claude, opus)."""
    with patch("crucis.intake.scaffold.sys") as mock_sys, \
         patch("crucis.display.prompt_input", side_effect=["", ""]), \
         patch("builtins.print"):
        mock_sys.stdin.isatty.return_value = True
        agent, model = prompt_model_selection()
    assert agent == "claude"
    assert model == "claude-opus-4-6"


def test_render_settings_template_substitutes_values():
    """Settings template should have agent/model values filled in."""
    result = _render_settings_template(agent="claude", model="claude-sonnet-4-6")
    parsed = yaml.safe_load(result)
    agents = parsed["agents"]
    assert agents["generation_agent"] == "claude"
    assert agents["critic_agent"] == "claude"
    assert agents["implementation_agent"] == "claude"
    assert agents["generation_model"] == "claude-sonnet-4-6"
    assert agents["critic_model"] == "claude-sonnet-4-6"
    assert agents["implementation_model"] == "claude-sonnet-4-6"


def test_render_settings_template_none_keeps_null():
    """Settings template should keep null when agent/model are None."""
    result = _render_settings_template()
    parsed = yaml.safe_load(result)
    agents = parsed["agents"]
    assert agents["generation_agent"] is None
    assert agents["generation_model"] is None


def test_scaffold_workspace_with_model_writes_settings(tmp_path):
    """scaffold_workspace with agent/model should write configured settings."""
    scaffold_workspace(
        tmp_path, name="demo", existing_codebase=False,
        agent="codex", model="o4-mini", include_settings=True,
    )
    settings = yaml.safe_load(
        (tmp_path / ".crucis" / "settings.yaml").read_text(encoding="utf-8")
    )
    assert settings["agents"]["generation_agent"] == "codex"
    assert settings["agents"]["generation_model"] == "o4-mini"
