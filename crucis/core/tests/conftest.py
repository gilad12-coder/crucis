"""Shared fixtures for core loop tests."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _skip_preflight():
    """Disable preflight diagnostics in unit tests."""
    with patch("crucis.core.loop._run_preflight"):
        yield
