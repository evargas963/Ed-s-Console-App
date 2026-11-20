"""COH-SA TIER-1.5: numeric_contract float parsing and triplet direction."""

from __future__ import annotations

import math
from decimal import Decimal
from fractions import Fraction

import numpy as np
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
        (True, None),
        (0, 0.0),
        (-1.5, -1.5),
        ("0.25", None),  # text is never read as a number
    ],
)
def test_float_finite_or_none(value, expected):
    got = float_finite_or_none(value)
    if expected is None:
        assert got is None
    else:
        assert got == expected
        assert math.isfinite(got)


class _OurFloat(float):
    """A float of another type (numpy's float64 is one)."""


@pytest.mark.parametrize(
    "value,expected",
    [
        # every real number a caller can hold: as a Python float, every digit kept
        (0.1, 0.1),
        (-0.0, -0.0),
        (1e308, 1e308),
        (5e-324, 5e-324),
        (-999.0, -999.0),  # not Schwab's field: Schwab's marker is schwab_number's
        (-999, -999.0),
        (7, 7.0),
        (2**53 + 1, float(2**53 + 1)),
        (np.float64(0.25), 0.25),
        (np.float32(0.5), 0.5),
        (np.int64(3), 3.0),
        (np.int32(-4), -4.0),
        (Fraction(1, 4), 0.25),
        (_OurFloat(1.5), 1.5),
        # not finite
        (float("nan"), None),
        (float("inf"), None),
        (float("-inf"), None),
        (np.float64("nan"), None),
        (np.float64("inf"), None),
        (_OurFloat("nan"), None),
        # not a number
        (None, None),
        (True, None),
        (False, None),
        (np.bool_(True), None),
        (Decimal("1.5"), None),  # a Decimal is not a real number of Python's (numbers.Real)
        (1 + 2j, None),
        ("1.5", None),
        (b"1.5", None),
        ([1.0], None),
        ({"v": 1.0}, None),
    ],
)
def test_float_finite_or_none_on_every_type_of_value(value, expected):
    """A real number (Python's numbers.Real, a bool not one) is its float when finite; else None.

    A number comes back as a Python float, its value exactly, whatever type held it.
    """
    got = float_finite_or_none(value)
    if expected is None:
        assert got is None
    else:
        assert type(got) is float
        assert got == expected and math.copysign(1.0, got) == math.copysign(1.0, expected)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (0, None),
        (-1.0, None),
        (float("nan"), None),
        (1e-6, 1e-6),
        (1700000000.5, 1700000000.5),
        ("1700000000.5", None),
    ],
)
def test_float_positive_or_none(value, expected):
    assert float_positive_or_none(value) == expected
