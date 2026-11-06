"""Numeric parsing. Schwab fields: `schwab_number` / `schwab_count` only (AGENTS.md rule 2,
enforced by tools/check_vendor_field_coercion.py)."""

from __future__ import annotations

import math
import numbers
from typing import (
    Any,
)


def float_finite_or_none(value: Any) -> float | None:
    """A number of ours as a float: None when it is not a number (None, text, a bool) or not
    finite. Text is never read as a number."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    v = float(value)
    return v if math.isfinite(v) else None


#: Schwab's own "no value" marker (greeks, IV, and any field Schwab could not fill).
SCHWAB_NO_VALUE = -999


def schwab_number(value: Any) -> float | None:
    """A Schwab field as sent (AGENTS.md rule 2): None when absent, -999, text, a bool, NaN or
    infinity; every other number exactly as sent, a reported 0 included."""
    if isinstance(value, float):
        return value if math.isfinite(value) and value != SCHWAB_NO_VALUE else None
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return None
    if isinstance(value, int):
        return None if value == SCHWAB_NO_VALUE else float(value)
    return None  # a list or an object: JSON's other kinds are not a number


def schwab_count(value: Any) -> float | None:
    """A Schwab volume, size or open interest as sent: schwab_number, and None when negative
    (Schwab's field definition excludes it; none was sent in 108 million captured messages,
    measured); a reported 0 is 0."""
    v = schwab_number(value)
    return v if v is not None and v >= 0.0 else None


def float_positive_or_none(value: Any) -> float | None:
    """Parse float; require finite value strictly greater than zero."""
    v = float_finite_or_none(value)
    return v if v is not None and v > 0.0 else None


def price_text(value: float | None) -> str | None:
    """A price as the screen shows it: two decimals. The value keeps every digit; only this text
    rounds. None when there is no price, which the page draws as missing."""
    if value is None:
        return None
    return f"{float(value):.2f}"


def shares_text(value: float | None) -> str | None:
    """A count of shares as the screen shows it: whole, with thousands separators (5,100). None
    when there is no count."""
    if value is None:
        return None
    return f"{float(value):,.0f}"


def percent_text(value: float | None) -> str | None:
    """A signed percentage as the screen shows it, whole (+22%, -21%, 0%). None when there is
    none."""
    if value is None:
        return None
    whole = math.floor(abs(float(value)) + 0.5)
    return "0%" if whole == 0 else f"{'+' if value > 0 else '-'}{whole}%"
