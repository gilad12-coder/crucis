"""Tests for Layer 1 module-level metric constraints."""

from crucis.constraints.checker import check_constraints
from crucis.models import ConstraintSet, TaskConstraints

_FEW_IMPORTS = """\
import os

def hello():
    return os.getcwd()
"""

_MANY_IMPORTS = """\
import os
import sys
import json
import pathlib
import collections
import itertools
import functools
import typing
import re
import math
import hashlib
"""

_FROM_IMPORTS = """\
from os import path
from os import getcwd
from collections import defaultdict
"""

_SIMPLE_CODE = """\
def add(a, b):
    return a + b
"""

_COMPLEX_CODE = """\
def spaghetti(x, y, z, w, v, u, t, s):
    if x > 0:
        if y > 0:
            if z > 0:
                if w > 0:
                    if v > 0:
                        if u > 0:
                            if t > 0:
                                if s > 0:
                                    return x + y + z + w + v + u + t + s
                                return -1
                            return -2
                        return -3
                    return -4
                return -5
            return -6
        return -7
    return -8
"""


def _make_constraints(**kwargs):
    """Build a TaskConstraints with given primary constraints.

    Returns:
        TaskConstraints with the specified primary constraints.
    """
    return TaskConstraints(
        primary=ConstraintSet(**kwargs),
        secondary=ConstraintSet(),
        target_files=[],
    )


class TestEfferentCoupling:
    """Tests for max_efferent_coupling constraint."""

    def test_few_imports_passes(self):
        """Verify module with few imports passes."""
        c = _make_constraints(max_efferent_coupling=5)
        primary, _ = check_constraints(_FEW_IMPORTS, c)
        assert primary.passed

    def test_many_imports_fails(self):
        """Verify module with too many imports fails."""
        c = _make_constraints(max_efferent_coupling=5)
        primary, _ = check_constraints(_MANY_IMPORTS, c)
        assert not primary.passed
        assert any("imports" in v and "modules" in v for v in primary.violations)

    def test_from_imports_deduplicated(self):
        """Verify multiple imports from same module count as one."""
        c = _make_constraints(max_efferent_coupling=2)
        primary, _ = check_constraints(_FROM_IMPORTS, c)
        assert primary.passed
        assert primary.metrics["efferent_coupling"] == 2  # os, collections

    def test_metric_recorded(self):
        """Verify coupling metric is recorded."""
        c = _make_constraints(max_efferent_coupling=100)
        primary, _ = check_constraints(_MANY_IMPORTS, c)
        assert primary.metrics["efferent_coupling"] == 11


class TestMaintainabilityIndex:
    """Tests for min_maintainability_index constraint."""

    def test_simple_code_passes(self):
        """Verify simple code has high maintainability index."""
        c = _make_constraints(min_maintainability_index=20.0)
        primary, _ = check_constraints(_SIMPLE_CODE, c)
        assert primary.passed
        assert primary.metrics["maintainability_index"] > 20.0

    def test_complex_code_fails(self):
        """Verify complex code fails high MI threshold."""
        c = _make_constraints(min_maintainability_index=80.0)
        primary, _ = check_constraints(_COMPLEX_CODE, c)
        assert not primary.passed
        assert any("Maintainability" in v for v in primary.violations)

    def test_metric_recorded(self):
        """Verify MI metric is recorded."""
        c = _make_constraints(min_maintainability_index=0.0)
        primary, _ = check_constraints(_SIMPLE_CODE, c)
        assert "maintainability_index" in primary.metrics
