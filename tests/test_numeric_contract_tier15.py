"""COH-SA TIER-1.5: numeric_contract float parsing and triplet direction."""

from __future__ import annotations

import math

import pytest

from numeric_contract import (
    direction_from_normalized_triplet,
    direction_from_triplet,
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
    "up,down,flat,expected",
    [
        (None, None, None, None),
        (0.5, 0.3, 0.2, "up"),
        (0.2, 0.25, 0.55, "flat"),
        (0.33, 0.33, 0.34, "flat"),
        (0.34, 0.33, 0.33, "up"),
    ],
)
def test_direction_from_triplet(up, down, flat, expected):
    assert direction_from_triplet(up, down, flat) == expected


def test_direction_from_triplet_rejects_nan_legs():
    assert direction_from_triplet(float("nan"), 0.5, 0.5) == "down"


def test_direction_from_triplet_tie_break_up_first():
    assert direction_from_triplet(1 / 3, 1 / 3, 1 / 3) == "up"
    assert direction_from_normalized_triplet(1 / 3, 1 / 3, 1 / 3) == "up"


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


def test_dominant_direction_withholds_on_nan_leg():
    """RC-363: math_probabilities.dominant_direction mirrors the WITHHELD policy
    instead of KeyError on the None label."""
    from math_probabilities import dominant_direction

    assert dominant_direction(float("nan"), 0.2, 0.2) == (None, None)
    assert dominant_direction(0.5, 0.3, 0.2) == ("up", 0.5)


def test_direction_from_triplet_dict_insertion_order_independent():
    """Tie-break is label order (up, down, flat), not caller dict order."""
    assert direction_from_triplet(0.4, 0.4, 0.2) == "up"
    assert direction_from_triplet(0.2, 0.4, 0.4) == "down"


def test_realized_eval_style_nan_now_rejected():
    """realized_contract_eval._f now uses finite parser — NaN must not pass."""
    from realized_contract_eval import _f

    assert _f(float("nan")) is None
    assert _f(float("inf")) is None
    assert _f(-2.5) == -2.5
