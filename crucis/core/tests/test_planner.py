"""Tests for generation plan builder helpers."""

from pathlib import Path

from crucis.core.planner import _extract_markdown, load_plan, write_plan_to_workspace


class TestExtractMarkdown:
    """Tests for _extract_markdown fence stripping."""

    def test_markdown_fenced_block(self):
        """Markdown-fenced content should strip the opening and closing fence."""
        text = "```markdown\n# Plan\n\n- step one\n- step two\n```"
        assert _extract_markdown(text) == "# Plan\n\n- step one\n- step two"

    def test_md_fenced_block(self):
        """Shorthand md-fenced content should strip the opening and closing fence."""
        text = "```md\n# Plan\n\n- step one\n```"
        assert _extract_markdown(text) == "# Plan\n\n- step one"

    def test_bare_fenced_block(self):
        """Bare triple-backtick wrapping should strip the fence pair."""
        text = "```\n# Plan\n\n- step one\n```"
        assert _extract_markdown(text) == "# Plan\n\n- step one"

    def test_no_fence(self):
        """Plain text without fences should be returned stripped."""
        text = "  # Plan\n\n- step one  "
        assert _extract_markdown(text) == "# Plan\n\n- step one"

    def test_empty_input(self):
        """Empty or whitespace-only input should return an empty string."""
        assert _extract_markdown("") == ""
        assert _extract_markdown("   ") == ""

    def test_markdown_fence_no_newline(self):
        """A markdown fence with no newline after tag should return empty string."""
        assert _extract_markdown("```markdown") == ""

    def test_bare_fence_no_newline(self):
        """A bare fence with no newline should return empty string."""
        assert _extract_markdown("```") == ""

    def test_markdown_fence_no_closing(self):
        """Markdown fence without closing backticks should return inner content."""
        text = "```markdown\n# Plan\nsome content"
        result = _extract_markdown(text)
        assert "# Plan" in result
        assert "some content" in result


class TestPlanFileIO:
    """Tests for write_plan_to_workspace / load_plan round-trip."""

    def test_round_trip(self, tmp_path: Path):
        """Written plan should be loadable with identical content.

        Args:
            tmp_path: Temporary directory provided by pytest.
        """
        content = "# My Plan\n\n- step one\n- step two\n"
        write_plan_to_workspace(content, tmp_path)
        loaded = load_plan(tmp_path)
        assert loaded == content

    def test_write_creates_directory(self, tmp_path: Path):
        """write_plan_to_workspace should create missing parent directories.

        Args:
            tmp_path: Temporary directory provided by pytest.
        """
        nested = tmp_path / "deep" / "nested"
        path = write_plan_to_workspace("content", nested)
        assert path.exists()
        assert path.name == "plan.md"

    def test_load_returns_none_when_missing(self, tmp_path: Path):
        """load_plan should return None when no plan file exists.

        Args:
            tmp_path: Temporary directory provided by pytest.
        """
        assert load_plan(tmp_path) is None

    def test_write_returns_path(self, tmp_path: Path):
        """write_plan_to_workspace should return the path to the written file.

        Args:
            tmp_path: Temporary directory provided by pytest.
        """
        path = write_plan_to_workspace("test", tmp_path)
        assert path == tmp_path / "plan.md"
