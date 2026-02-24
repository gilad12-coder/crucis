"""Tests for runtime settings loader/persistence."""

from pathlib import Path

import pytest
import yaml

from crucis.persistence.settings import (
    RuntimeSettings,
    load_runtime_settings,
    settings_path,
)


def test_load_runtime_settings_writes_defaults(tmp_path: Path):
    """Missing settings file should be created with defaults.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    settings = load_runtime_settings(tmp_path)
    path = settings_path(tmp_path)
    assert path.exists()
    assert isinstance(settings, RuntimeSettings)
    assert settings.optimizer.max_metric_calls == 24
    assert settings.optimizer.promotion_mode == "manual"


def test_load_runtime_settings_reads_user_overrides(tmp_path: Path):
    """User-edited settings should round-trip through the loader.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    path = settings_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "optimizer": {
                    "enabled": True,
                    "max_metric_calls": 60,
                    "reflection_lm": "openai/gpt-4.1-mini",
                    "train_split_ratio": 0.6,
                    "min_score_delta": 0.02,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    settings = load_runtime_settings(tmp_path)
    assert settings.optimizer.max_metric_calls == 60
    assert settings.optimizer.reflection_lm == "openai/gpt-4.1-mini"
    assert settings.optimizer.train_split_ratio == pytest.approx(0.6)


def test_load_runtime_settings_rejects_invalid_weights(tmp_path: Path):
    """Invalid scoring weights should raise a validation error.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    path = settings_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "optimizer": {
                    "pass_weight": 0.0,
                    "speed_weight": 0.0,
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises((ValueError, TypeError)):
        load_runtime_settings(tmp_path)


