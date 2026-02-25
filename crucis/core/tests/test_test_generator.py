import ast

from crucis.core.test_generator import (
    build_generation_prompt,
    extract_python_from_response,
)
from crucis.models import ConstraintSet, ParsedObjective, TaskConstraints

# --- Unit tests: prompt construction and code extraction ---


class TestBuildGenerationPrompt:
    """Tests for build_generation_prompt."""

    def test_build_generation_prompt_contains_name_and_pytest(
        self, minimal_spec, minimal_constraints
    ):
        """Test that build_generation_prompt includes the function name and pytest.

        Args:
            minimal_spec: Minimal ParsedObjective fixture.
            minimal_constraints: Minimal TaskConstraints fixture.
        """
        prompt = build_generation_prompt(minimal_spec, minimal_constraints)
        assert isinstance(prompt, str)
        assert minimal_spec.name in prompt
        assert "pytest" in prompt.lower()

    def test_build_generation_prompt_includes_primary_constraints(
        self, minimal_spec, minimal_constraints
    ):
        """Test that build_generation_prompt includes primary constraint values.

        Args:
            minimal_spec: Minimal ParsedObjective fixture.
            minimal_constraints: Minimal TaskConstraints fixture.
        """
        prompt = build_generation_prompt(minimal_spec, minimal_constraints)
        assert str(minimal_constraints.primary.max_cyclomatic_complexity) in prompt

    def test_build_generation_prompt_includes_secondary_constraints(
        self, minimal_spec, minimal_constraints
    ):
        """Test that build_generation_prompt includes secondary constraint names.

        Args:
            minimal_spec: Minimal ParsedObjective fixture.
            minimal_constraints: Minimal TaskConstraints fixture.
        """
        prompt = build_generation_prompt(minimal_spec, minimal_constraints)
        assert "docstring" in prompt.lower()

    def test_build_generation_prompt_includes_examples(self, minimal_spec, minimal_constraints):
        """Test that build_generation_prompt includes spec examples.

        Args:
            minimal_spec: Minimal ParsedObjective fixture.
            minimal_constraints: Minimal TaskConstraints fixture.
        """
        prompt = build_generation_prompt(minimal_spec, minimal_constraints)
        assert "1, 2" in prompt or "(1, 2)" in prompt

    def test_build_generation_prompt_distinguishes_required_and_advisory(
        self, minimal_spec, minimal_constraints
    ):
        """Test that build_generation_prompt labels required and advisory sections.

        Args:
            minimal_spec: Minimal ParsedObjective fixture.
            minimal_constraints: Minimal TaskConstraints fixture.
        """
        prompt = build_generation_prompt(minimal_spec, minimal_constraints)
        assert "required" in prompt.lower()
        assert "advisory" in prompt.lower()

    def test_build_generation_prompt_includes_guidance(self, minimal_spec):
        """Test that build_generation_prompt includes guidance strings.

        Args:
            minimal_spec: Minimal ParsedObjective fixture.
        """
        constraints = TaskConstraints(
            primary=ConstraintSet(max_cyclomatic_complexity=5),
            secondary=ConstraintSet(),
            target_files=[],
            guidance=["Prefer early returns.", "Avoid inline comments."],
        )
        prompt = build_generation_prompt(minimal_spec, constraints)
        assert "Prefer early returns." in prompt
        assert "Avoid inline comments." in prompt

    def test_build_generation_prompt_includes_time_complexity(self, minimal_spec):
        """Test that build_generation_prompt includes time complexity constraints.

        Args:
            minimal_spec: Minimal ParsedObjective fixture.
        """
        constraints = TaskConstraints(
            primary=ConstraintSet(max_time_complexity="O(n)"),
            secondary=ConstraintSet(),
            target_files=[],
        )
        prompt = build_generation_prompt(minimal_spec, constraints)
        assert "O(n)" in prompt

    def test_build_generation_prompt_excludes_hidden_eval_literals(self, minimal_constraints):
        """Test that holdout eval values are not shown in generation prompt.

        Args:
            minimal_constraints: Minimal TaskConstraints fixture.
        """
        spec = ParsedObjective(
            name="add",
            description="Add two numbers",
            train_evals=[{"input": "(1, 2)", "output": "3"}],
            holdout_evals=[{"input": "(100, 200)", "output": "300"}],
        )
        prompt = build_generation_prompt(spec, minimal_constraints)
        assert "(1, 2)" in prompt
        assert "100" not in prompt
        assert "300" not in prompt


class TestExtractPythonFromResponse:
    """Tests for extract_python_from_response."""

    def test_extract_python_from_code_fence(self):
        """Test that extract_python_from_response extracts code from fenced blocks."""
        response = (
            "Here are the tests:\n\n```python\nimport pytest\n\n"
            "def test_add():\n    assert 1 + 1 == 2\n```\n\nDone."
        )
        code = extract_python_from_response(response)
        assert "import pytest" in code
        assert "def test_add" in code

    def test_extract_python_from_raw_code(self):
        """Test that extract_python_from_response handles raw Python code."""
        response = "import pytest\n\ndef test_add():\n    assert 1 + 1 == 2\n"
        code = extract_python_from_response(response)
        assert "import pytest" in code

    def test_extract_python_from_response_validates_syntax(self):
        """Test that extracted Python code is syntactically valid."""
        response = "```python\nimport pytest\n\ndef test_add():\n    assert 1 + 1 == 2\n```"
        code = extract_python_from_response(response)
        ast.parse(code)

    def test_extract_python_from_response_multiple_code_blocks(self):
        """Test that extract_python_from_response handles multiple code blocks."""
        response = (
            "```python\nimport pytest\n```\n\nAnd more:\n\n"
            "```python\ndef test_add():\n    assert 1 + 1 == 2\n```"
        )
        code = extract_python_from_response(response)
        assert "def test_" in code
