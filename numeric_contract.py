"""Numeric parsing.

Schwab fields: `schwab_number`, `schwab_count` and `schwab_time_ms` only (AGENTS.md rule 2).
"""

from __future__ import annotations

import math
import numbers
from decimal import Decimal
from typing import (
    Any,
    overload,
)


def float_finite_or_none(value: Any) -> float | None:
    """Return a number of ours as a float.

    None when it is not a number (None, text, a bool) or not finite. Text is never read as a
    number.
    """
    if isinstance(value, float):  # a float, numpy's float64 included: one C type check
        return float(value) if math.isfinite(value) else None
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    v = float(value)
    return v if math.isfinite(v) else None


#: Schwab's own "no value" marker (greeks, IV, and any field Schwab could not fill).
SCHWAB_NO_VALUE: float = -999


def schwab_number(value: Any) -> float | None:
    """Return a Schwab field as sent (AGENTS.md rule 2).

    None when absent, -999, text, a bool, NaN or infinity; every other number exactly as sent, a
    reported 0 included.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) and value != SCHWAB_NO_VALUE else None
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return None
    if isinstance(value, int):
        return None if value == SCHWAB_NO_VALUE else float(value)
    return None  # a list or an object: JSON's other kinds are not a number


def schwab_count(value: Any) -> float | None:
    """Return a Schwab volume, size, open interest or strike as sent.

    schwab_number, and None when negative (Schwab's field definition excludes it: a count is
    never negative, none was sent in 108 million captured messages, measured; a strike is
    written unsigned in the option symbol, Streamer API §3.2); a reported 0 is 0.
    """
    v = schwab_number(value)
    return v if v is not None and v >= 0.0 else None


def schwab_time_ms(value: Any) -> float | None:
    """Return a Schwab time, milliseconds since the epoch, as sent.

    schwab_number, and None at 0 or before. Each of Schwab's times is when an event occurred
    (Streamer API §3.1, field 34: "Last time a bid or ask updated"), and Schwab sends 0 where none
    has: an index, which has no bid or ask, is sent a quote time of 0. A time of 0 is not one.
    """
    v = schwab_number(value)
    return v if v is not None and v > 0.0 else None


def float_positive_or_none(value: Any) -> float | None:
    """Parse float; require finite value strictly greater than zero."""
    v = float_finite_or_none(value)
    return v if v is not None and v > 0.0 else None


@overload
def price_text(value: float) -> str: ...
@overload
def price_text(value: None) -> None: ...
@overload
def price_text(value: float | None) -> str | None: ...
def price_text(value: float | None) -> str | None:
    """Return a price as the screen shows it: two decimals.

    The value keeps every digit; only this text rounds. None when there is no price, which the
    page draws as missing.
    """
    if value is None:
        return None
    return f"{float(value):.2f}"


@overload
def strike_text(value: float) -> str: ...
@overload
def strike_text(value: None) -> None: ...
@overload
def strike_text(value: float | None) -> str | None: ...
def strike_text(value: float | None) -> str | None:
    """Return a strike as the heatmap lists it: to the cent, no trailing zeros (397.5, 400).

    None when there is no strike.
    """
    if value is None:
        return None
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def iv_text(value: float | None) -> str | None:
    """Return an implied volatility (a percent) as the screen shows it: two decimals, as a price.

    None when there is none.
    """
    return price_text(value)


def greek_text(value: float | None) -> str | None:
    """Return a Greek as the screen shows it: every digit Schwab sent, as a plain decimal.

    The shortest digits that read back as the same number, never rounded and never in exponent
    form: 0.00000001, 0.5123, -1. None when there is none.
    """
    if value is None:
        return None
    return format(Decimal(repr(float(value))).normalize(), "f")


def fixed_text(value: float | None, places: int) -> str | None:
    """Return a measure with no unit of its own as the screen shows it: `places` decimals.

    A ratio, an imbalance, a pressure or a share. None when there is none.
    """
    if value is None:
        return None
    return f"{float(value):.{places}f}"


def count_text(value: float | None) -> str | None:
    """Return a count (shares, contracts, open interest, volume) as the screen shows it.

    Whole, with thousands separators, so every unit it moves by shows: 20,010, -1,200, 950.
    None when there is no count.
    """
    if value is None:
        return None
    return f"{float(value):,.0f}"


def compact_text(value: float | None) -> str | None:
    """Return an estimate (an exposure in delta-shares) as the screen shows it, compact.

    Two decimals in thousands, millions and billions, whole below a thousand: 1.23B, -4.56M,
    7.89K, 950. None when there is none.
    """
    if value is None:
        return None
    v = float(value)
    sign, a = ("-" if v < 0 else ""), abs(v)
    for size, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= size:
            return f"{sign}{a / size:.2f}{unit}"
    return f"{sign}{a:.0f}"


@overload
def dollars_text(value: float) -> str: ...
@overload
def dollars_text(value: None) -> None: ...
@overload
def dollars_text(value: float | None) -> str | None: ...
def dollars_text(value: float | None) -> str | None:
    """Return dollars as the screen shows them, compact as compact_text: $1.23B, -$4.56M, $950.

    None when there is no amount.
    """
    text = compact_text(value)
    if text is None:
        return None
    return f"-${text[1:]}" if text.startswith("-") else f"${text}"


def change_percent_text(value: float | None) -> str | None:
    """Return a percent change as the screen shows it: signed, two decimals (+0.57%, -1.25%).

    None when there is none.
    """
    if value is None:
        return None
    return f"{float(value):+.2f}%"


@overload
def signed_text(value: float, places: int) -> str: ...
@overload
def signed_text(value: None, places: int) -> None: ...
@overload
def signed_text(value: float | None, places: int) -> str | None: ...
def signed_text(value: float | None, places: int) -> str | None:
    """Return a change or a lean as the screen shows it: signed, `places` decimals (+0.23, -1.20).

    None when there is none.
    """
    if value is None:
        return None
    return f"{float(value):+.{places}f}"


@overload
def share_text(fraction: float) -> str: ...
@overload
def share_text(fraction: None) -> None: ...
@overload
def share_text(fraction: float | None) -> str | None: ...
def share_text(fraction: float | None) -> str | None:
    """Return a share of a whole, a fraction from 0 to 1, as the screen shows it: whole ("62%").

    None when there is none.
    """
    if fraction is None:
        return None
    return f"{float(fraction):.0%}"


def percent_text(value: float | None) -> str | None:
    """Return a signed percentage as the screen shows it, whole (+22%, -21%, 0%).

    None when there is none.
    """
    if value is None:
        return None
    whole = math.floor(abs(float(value)) + 0.5)
    return "0%" if whole == 0 else f"{'+' if value > 0 else '-'}{whole}%"
