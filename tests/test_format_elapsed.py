"""Tests for format_elapsed duration formatting."""

import pytest

from crucis.display import format_elapsed


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0, "0s"),
        (1, "1s"),
        (5, "5s"),
        (59, "59s"),
    ],
    ids=["zero", "one", "five", "fifty_nine"],
)
def test_returns_seconds_only(seconds: float, expected: str) -> None:
    """Verify durations under 60s format as '{n}s'.

    Args:
        seconds: Input duration in seconds.
        expected: Expected formatted string.
    """
    assert format_elapsed(seconds) == expected


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (60, "1m"),
        (61, "1m 1s"),
        (120, "2m"),
        (154, "2m 34s"),
        (180, "3m"),
        (3599, "59m 59s"),
    ],
    ids=["one_min_exact", "one_min_one_sec", "two_min_exact", "two_min_34s", "three_min_exact", "just_under_hour"],
)
def test_minutes_and_seconds(seconds: float, expected: str) -> None:
    """Verify durations from 60s to 3599s format as '{m}m {s}s' or '{m}m'.

    Args:
        seconds: Input duration in seconds.
        expected: Expected formatted string.
    """
    assert format_elapsed(seconds) == expected


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (3600, "1h"),
        (3601, "1h 0m"),
        (4320, "1h 12m"),
        (7200, "2h"),
        (7261, "2h 1m"),
    ],
    ids=["one_hour_exact", "one_hour_one_sec", "one_hour_12m", "two_hours_exact", "two_hours_one_min"],
)
def test_hours_and_minutes(seconds: float, expected: str) -> None:
    """Verify durations of 3600s+ format as '{h}h {m}m' or '{h}h'.

    Args:
        seconds: Input duration in seconds.
        expected: Expected formatted string.
    """
    assert format_elapsed(seconds) == expected


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0.5, "0s"),
        (0.9, "0s"),
        (59.5, "59s"),
        (59.999, "59s"),
        (60.7, "1m 0s"),
        (3600.9, "1h 0m"),
    ],
    ids=["half_sec", "point_nine", "59_point_5", "59_point_999", "60_point_7", "3600_point_9"],
)
def test_truncates_fractional_seconds(seconds: float, expected: str) -> None:
    """Verify fractional seconds are truncated, not rounded.

    Args:
        seconds: Input duration with fractional part.
        expected: Expected formatted string after truncation.
    """
    assert format_elapsed(seconds) == expected


@pytest.mark.parametrize(
    "seconds",
    [-1, -0.1, -3600],
    ids=["neg_one", "neg_fraction", "neg_hour"],
)
def test_raises_value_error(seconds: float) -> None:
    """Verify negative input raises ValueError.

    Args:
        seconds: Negative input duration.
    """
    with pytest.raises(ValueError):
        format_elapsed(seconds)
