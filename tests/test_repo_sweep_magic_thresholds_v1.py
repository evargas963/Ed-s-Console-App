"""Schwab's missing-greek code is -999.0."""

from __future__ import annotations

import pytest

from math_exposure_core import MISSING_GREEK_SENTINEL


def test_missing_greek_sentinel_constant_value_is_negative_999_point_0():
    assert pytest.approx(-999.0) == MISSING_GREEK_SENTINEL
