"""Module-level metric checkers for Layer 1 universal design constraints."""

import ast

from radon.metrics import mi_visit

from crucis.models import ConstraintSet


def _chk_efferent_coupling(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    if cs.max_efferent_coupling is None:
        return
    count = _count_efferent_coupling(src)
    m["efferent_coupling"] = count
    if count > cs.max_efferent_coupling:
        v.append(
            f"Module imports {count} distinct modules"
            f" — max {cs.max_efferent_coupling}; reduce external dependencies"
        )


def _chk_maintainability_index(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    if cs.min_maintainability_index is None:
        return
    mi = _compute_maintainability_index(src)
    m["maintainability_index"] = round(mi, 2)
    if mi < cs.min_maintainability_index:
        v.append(
            f"Maintainability index {mi:.1f} is below minimum"
            f" {cs.min_maintainability_index}"
            " — reduce complexity, shorten functions, or add comments"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_efferent_coupling(src: str) -> int:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return 0
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # e.g. "import os.path" -> top-level module "os"
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module.split(".")[0])
    return len(modules)


def _compute_maintainability_index(src: str) -> float:
    try:
        return mi_visit(src, True)
    except Exception:
        return 100.0  # If analysis fails, don't penalize
