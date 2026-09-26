"""COH-SA TIER-1.5: numeric_contract float parsing and triplet direction."""

from __future__ import annotations

import math

import pytest

from numeric_contract import (
    float_finite_or_none,
    float_positive_or_none,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        ("nan", None),
        (float("nan"), None),
        (float("inf"), None),
        (float("-inf"), None),
        ("not-a-number", None),
        (0, 0.0),
        (-1.5, -1.5),
        ("0.25", 0.25),
    ],
)
def test_float_finite_or_none(value, expected):
    got = float_finite_or_none(value)
    if expected is None:
        assert got is None
    else:
        assert got == expected
        assert math.isfinite(got)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (0, None),
        (-1.0, None),
        (float("nan"), None),
        (1e-6, 1e-6),
        ("1700000000.5", 1700000000.5),
    ],
)
def test_float_positive_or_none(value, expected):
    assert float_positive_or_none(value) == expected














def test_realized_eval_style_nan_now_rejected():
    """realized_contract_eval._f now uses finite parser — NaN must not pass."""
    from realized_contract_eval import _f

    assert _f(float("nan")) is None
    assert _f(float("inf")) is None
    assert _f(-2.5) == -2.5
