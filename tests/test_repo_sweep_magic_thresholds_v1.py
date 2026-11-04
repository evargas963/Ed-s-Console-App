"""Schwab's missing-greek code is -999.0."""

from __future__ import annotations

import pytest

from numeric_contract import SCHWAB_NO_VALUE


def test_missing_greek_sentinel_constant_value_is_negative_999_point_0():
    assert pytest.approx(-999.0) == SCHWAB_NO_VALUE
