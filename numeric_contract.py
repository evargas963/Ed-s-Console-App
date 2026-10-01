"""Numeric parsing, and the one text of a price and of a volume. Schwab fields are read by
`schwab_number` / `schwab_count`; `float_finite_or_none` parses text and is never a reader of a
Schwab field."""

from __future__ import annotations

import math
from decimal import Decimal
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


def _exact(v: float) -> str:
    """Every digit of a number as sent (its shortest exact decimal), with thousands separators:
    9.59, -0.31185, 62,110,041, 7,671.5; never rounded, abbreviated or in exponent form."""
    return format(Decimal(repr(float(v))).normalize(), ",f")


def price_text(v: "float | None") -> str:
    """A price as every server-made text shows it: exactly as sent (operator 2026-10-01: "no
    rounding, use the exact data that schwab gives us everywhere"); "—" when there is none."""
    return "—" if v is None else _exact(v)


def volume_text(n: "float | None") -> str:
    """A volume or size (shares, contracts) as the screen shows it: exactly as sent, 62,110,041;
    "—" when there is none."""
    return "—" if n is None else _exact(n)


def percent_text(v: "float | None") -> str:
    """A percent Schwab sends (its change percents) as the screen shows it: signed, exactly as
    sent, -0.31185%, +0.5%; "—" when there is none."""
    return "—" if v is None else ("+" if v > 0 else "") + _exact(v) + "%"


def sign_word(v: "float | None") -> "str | None":
    """The direction of a signed value, for the screen's colour: pos, neg, flat; None when there is
    none."""
    return None if v is None else "pos" if v > 0 else "neg" if v < 0 else "flat"


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









