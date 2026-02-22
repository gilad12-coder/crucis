"""Tests for optimizer policy persistence and env overrides."""

import json
from pathlib import Path

import pytest

from crucis.persistence.policy import (
    MAX_POLICY_FIELD_CHARS,
    POLICY_OVERRIDE_ENV,
    OptimizerPolicy,
    load_active_policy,
    load_candidate_policy,
    save_active_policy,
    save_candidate_policy,
)


def test_save_and_load_active_policy_roundtrip(tmp_path: Path):
    """Persisted active policy should load back unchanged.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    policy = OptimizerPolicy(
        repository_skill="Use focused edits.",
        generation_directives="Prefer edge-case coverage.",
        adversary_directives="Probe for hardcoded outputs.",
        evaluation_directives="Implement true behavior.",
    )

    save_active_policy(policy, tmp_path)
    loaded = load_active_policy(tmp_path, allow_env_override=False)
    assert loaded == policy


def test_load_active_policy_env_override_precedence(tmp_path: Path, monkeypatch):
    """CRUCIS_POLICY_OVERRIDE_JSON should override on-disk policy when enabled.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture.
    """
    save_active_policy(
        OptimizerPolicy(repository_skill="disk"),
        tmp_path,
    )

    override = {
        "repository_skill": "env",
        "generation_directives": "gen",
        "adversary_directives": "adv",
        "evaluation_directives": "eval",
    }
    monkeypatch.setenv(POLICY_OVERRIDE_ENV, json.dumps(override))

    loaded = load_active_policy(tmp_path, allow_env_override=True)
    assert loaded.repository_skill == "env"
    assert loaded.generation_directives == "gen"


def test_policy_field_size_cap_enforced():
    """Oversized policy sections should be rejected."""
    oversize = "x" * (MAX_POLICY_FIELD_CHARS + 1)
    with pytest.raises((ValueError, TypeError)):
        OptimizerPolicy(repository_skill=oversize)


def test_from_candidate_requires_exact_keys():
    """Candidate mapping must contain exactly the 4 policy fields."""
    with pytest.raises(ValueError):
        OptimizerPolicy.from_candidate({"repository_skill": "only-one"})


def test_save_and_load_candidate_policy_roundtrip(tmp_path: Path):
    """Candidate policy artifacts should be persisted per optimizer run.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    policy = OptimizerPolicy(repository_skill="candidate")
    save_candidate_policy(policy, tmp_path, "run-123")
    loaded = load_candidate_policy(tmp_path, "run-123")
    assert loaded.repository_skill == "candidate"
