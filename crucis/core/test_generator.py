"""LLM-based test generation: prompt dispatch and Python extraction."""

import ast
import re

from crucis.core.prompts import build_generation_prompt  # noqa: F401


def extract_python_from_response(response: str) -> str:
    """Extract Python source code from an LLM response.

    Args:
        response: LLM response text, possibly with markdown fences.

    Returns:
        Extracted Python code, or empty string if none found.
    """
    blocks = re.findall(r"```python\s*\n(.*?)```", response, re.DOTALL)
    if blocks:
        code = "\n\n".join(blocks)
        try:
            ast.parse(code)
            return code
        except SyntaxError:
            pass

    # Try raw response as Python
    try:
        ast.parse(response)
        return response
    except SyntaxError:
        pass

    return ""
