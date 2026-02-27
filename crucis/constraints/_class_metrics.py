"""Class-level metric checkers for Layer 1 universal design constraints."""

import ast

from radon.complexity import cc_visit

from crucis.models import ConstraintSet


def _chk_methods_per_class(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    if cs.max_methods_per_class is None:
        return
    worst_count, worst_name = _max_methods_per_class(src)
    m["methods_per_class"] = worst_count
    if worst_count > cs.max_methods_per_class:
        v.append(
            f"Class '{worst_name}' has {worst_count} methods"
            f" — max {cs.max_methods_per_class}; split into smaller classes"
        )


def _chk_fields_per_class(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    if cs.max_fields_per_class is None:
        return
    worst_count, worst_name = _max_fields_per_class(src)
    m["fields_per_class"] = worst_count
    if worst_count > cs.max_fields_per_class:
        v.append(
            f"Class '{worst_name}' has {worst_count} instance fields"
            f" — max {cs.max_fields_per_class}; group related fields into sub-objects"
        )


def _chk_class_lines(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    if cs.max_class_lines is None:
        return
    worst_count, worst_name = _max_class_lines(src)
    m["class_lines"] = worst_count
    if worst_count > cs.max_class_lines:
        v.append(
            f"Class '{worst_name}' is {worst_count} lines"
            f" — max {cs.max_class_lines}; extract responsibilities into separate classes"
        )


def _chk_weighted_methods_per_class(src: str, cs: ConstraintSet, v: list, m: dict) -> None:
    if cs.max_weighted_methods_per_class is None:
        return
    worst_wmc, worst_name = _max_weighted_methods_per_class(src)
    m["weighted_methods_per_class"] = worst_wmc
    if worst_wmc > cs.max_weighted_methods_per_class:
        v.append(
            f"Class '{worst_name}' has WMC {worst_wmc}"
            f" — max {cs.max_weighted_methods_per_class}; reduce method complexity"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _max_methods_per_class(src: str) -> tuple[int, str]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return 0, ""
    worst_count = 0
    worst_name = ""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        count = sum(
            1 for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        if count > worst_count:
            worst_count = count
            worst_name = node.name
    return worst_count, worst_name


def _max_fields_per_class(src: str) -> tuple[int, str]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return 0, ""
    worst_count = 0
    worst_name = ""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        fields: set[str] = set()
        # Count self.x assignments in __init__
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == "__init__":
                for stmt in ast.walk(child):
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if (
                                isinstance(target, ast.Attribute)
                                and isinstance(target.value, ast.Name)
                                and target.value.id == "self"
                            ):
                                fields.add(target.attr)
                    elif isinstance(stmt, ast.AnnAssign) and stmt.target is not None:
                        if (
                            isinstance(stmt.target, ast.Attribute)
                            and isinstance(stmt.target.value, ast.Name)
                            and stmt.target.value.id == "self"
                        ):
                            fields.add(stmt.target.attr)
        # Count class-level annotated fields (no value or simple value)
        for child in node.body:
            if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                fields.add(child.target.id)
        count = len(fields)
        if count > worst_count:
            worst_count = count
            worst_name = node.name
    return worst_count, worst_name


def _max_class_lines(src: str) -> tuple[int, str]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return 0, ""
    worst_count = 0
    worst_name = ""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if node.end_lineno is None:
            continue
        count = node.end_lineno - node.lineno + 1
        if count > worst_count:
            worst_count = count
            worst_name = node.name
    return worst_count, worst_name


def _max_weighted_methods_per_class(src: str) -> tuple[int, str]:
    try:
        blocks = cc_visit(src)
    except SyntaxError:
        return 0, ""
    # Group by classname and sum complexity
    class_wmc: dict[str, int] = {}
    for block in blocks:
        cname = getattr(block, "classname", None)
        if not cname:
            continue
        class_wmc[cname] = class_wmc.get(cname, 0) + block.complexity
    if not class_wmc:
        return 0, ""
    worst_name = max(class_wmc, key=class_wmc.get)  # type: ignore[arg-type]
    return class_wmc[worst_name], worst_name
