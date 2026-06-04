"""arch_competition.numeric_safe — shared defensive float coercion."""

from __future__ import annotations


import pytest

from arch_competition.numeric_safe import safe_float


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (0.5, 0.5),
        ("0.25", 0.25),
        (float("nan"), None),
        (float("inf"), None),
        ("abc", None),
        ("NaN", None),
    ],
)
def test_safe_float(value, expected):
    out = safe_float(value)
    if expected is None:
        assert out is None
    else:
        assert out == pytest.approx(expected)
