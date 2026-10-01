"""Numeric parsing, and the one text of a price and of a volume. Schwab fields are read by
`schwab_number` / `schwab_count`; `float_finite_or_none` parses text and is never a reader of a
Schwab field."""

from __future__ import annotations

import math
from typing import (
    Any,
)




def float_finite_or_none(value: Any) -> float | None:
    """Parse float; reject None, non-numeric, NaN, and ±inf."""
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def price_text(v: "float | None") -> str:
    """A price as every server-made text shows it: two decimals; "—" when there is none."""
    return "—" if v is None else f"{float(v):.2f}"


def volume_text(n: "float | None") -> str:
    """A volume (shares) as the screen shows it: 62.11M, 210.1K, 950; "—" when there is none."""
    if n is None:
        return "—"
    a = abs(float(n))
    for size, unit, places in ((1e9, "B", 2), (1e6, "M", 2), (1e3, "K", 1)):
        if a >= size:
            return f"{a / size:.{places}f}{unit}"
    return str(round(a))


#: Schwab's own "no value" marker (greeks, IV, and any field Schwab could not fill).
SCHWAB_NO_VALUE = -999


def schwab_number(value: Any) -> float | None:
    """A Schwab field as sent: None when absent, -999, text, a bool, NaN or
    infinity; every other number exactly as sent, a reported 0 included."""
    if value is None or isinstance(value, (bool, str)):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v != SCHWAB_NO_VALUE else None


def schwab_count(value: Any) -> float | None:
    """A Schwab volume, size or open interest as sent: schwab_number, and None when negative
    (Schwab's field definition excludes it; none was ever sent -- measured 2026-09-27 over
    108 million captured messages); a reported 0 is 0."""
    v = schwab_number(value)
    return v if v is not None and v >= 0.0 else None


def float_positive_or_none(value: Any) -> float | None:
    """Parse float; require finite value strictly greater than zero."""
    v = float_finite_or_none(value)
    return v if v is not None and v > 0.0 else None









