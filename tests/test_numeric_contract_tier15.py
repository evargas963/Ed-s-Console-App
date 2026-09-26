"""COH-SA TIER-1.5: numeric_contract float parsing and triplet direction."""

from __future__ import annotations

import math

import pytest

from numeric_contract import (
    direction_from_normalized_triplet,
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








@pytest.mark.parametrize(
    "up,down,flat",
    [
        (None, 0.2, 0.2),
        (0.6, None, 0.2),
        (0.6, 0.2, None),
        (None, None, None),
        (float("nan"), 0.2, 0.2),
        (0.6, float("inf"), 0.2),
        (0.6, 0.2, float("-inf")),
        ("0.6", 0.2, 0.2),
    ],
)
def test_direction_from_normalized_triplet_withholds_on_bad_leg(up, down, flat):
    """RC-363: single producer is defensive — any None / non-finite / non-numeric
    leg returns None (WITHHELD) instead of raising TypeError or emitting an
    order-dependent garbage label."""
    assert direction_from_normalized_triplet(up, down, flat) is None






def test_realized_eval_style_nan_now_rejected():
    """realized_contract_eval._f now uses finite parser — NaN must not pass."""
    from realized_contract_eval import _f

    assert _f(float("nan")) is None
    assert _f(float("inf")) is None
    assert _f(-2.5) == -2.5
