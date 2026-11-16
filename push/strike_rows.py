"""Every per-strike panel's rows: the window a page asks for, and each row as the page draws it."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any

from calc.terrain_engine import SCOPES, StrikeRow, StrikeValue, strike_window
from numeric_contract import compact_text, count_text, dollars_text, strike_text

#: why a strike window is not around the price
WINDOW_NO_PRICE = "no live price: the middle strikes of the chain"

#: a per-strike bar's row: each strike's value, with the GEX rows' volume beside it
type BarRow = StrikeValue | StrikeRow

#: each per-strike value as the screen shows it: GEX and DEX in dollars; open interest a count;
#: vanna and charm (delta-shares) compact
VALUE_TEXT = {
    "gex": dollars_text,
    "dex": dollars_text,
    "oi": count_text,
    "vanna_rows": compact_text,
    "charm_rows": compact_text,
}


def window(
    strikes: Collection[float],
    spot_strike: float | None,
    scope: str,
    centre: float | None,
    shift: int,
) -> tuple[int, int, dict[str, Any]]:
    """Every per-strike panel's rows.

    strike_window around the operator's panned `centre`, else the strike nearest the live price
    (`spot_strike`), moved `shift` rows. Returns (first index,
    last index, the view's {centre, note}): `note` says why the rows are not around the price
    (no price and no pan), else None.
    """
    lo, hi, c = strike_window(strikes, spot_strike if centre is None else centre, scope, shift)
    note = WINDOW_NO_PRICE if centre is None and spot_strike is None and strikes else None
    return lo, hi, {"centre": c, "centre_text": strike_text(c), "note": note}


def windowed[R: BarRow](
    rows: Sequence[R],
    spot_strike: float | None,
    scope: str,
    centre: float | None,
    shift: int,
) -> tuple[Sequence[R], dict[str, Any]]:
    """`rows` (ascending by strike) as a panel draws them.

    window's rows, with its view {centre, note, max_abs}: the centre strike (send it back to pan
    from it), why the rows are not around the price, and the largest |value| in the window (the
    bar and colour scale), None when no value is known.
    """
    lo, hi, view = window([r.strike for r in rows], spot_strike, scope, centre, shift)
    win = rows[lo : hi + 1]
    known = [abs(r.value) for r in win if r.value is not None]
    return win, {**view, "max_abs": max(known) if known else None}


def max_abs_served(rows: Sequence[BarRow], measure: str) -> dict[str, Any] | None:
    """Return the row with the largest |value| of every strike, served; None with no known value.

    Every row is looked at, on screen or not: the chart labels it.
    """
    known = [(abs(r.value), r) for r in rows if r.value is not None]
    if not known:
        return None
    return served(max(known, key=lambda size_row: size_row[0])[1], measure)


def served(row: BarRow, measure: str) -> dict[str, Any]:
    """Return a per-strike row as the page draws it: its fields by name, its value's text.

    A GEX row's volume is served with its text too. The page draws the texts; it formats none.
    """
    out = {
        **row._asdict(),
        "strike_text": strike_text(row.strike),
        "text": VALUE_TEXT[measure](row.value),
    }
    if isinstance(row, StrikeRow):
        out["volume_text"] = count_text(row.volume)
    return out


def window_asked(params: dict[str, Any]) -> tuple[str, float | None, int] | str:
    """Return the window a page's panel parameters ask for: (scope, centre, shift).

    The page sends all three: the scope, one of SCOPES; the centre, a strike or None (follow the
    price); the shift, a whole number of rows. Parameters that ask for none of these: the words
    saying which.
    """
    scope, centre, shift = params.get("scope"), params.get("centre"), params.get("shift")
    if scope not in SCOPES:
        return f"scope {scope!r} is not one of {', '.join(SCOPES)}"
    if centre is not None and (isinstance(centre, bool) or not isinstance(centre, int | float)):
        return f"centre {centre!r} is not a strike"
    if isinstance(shift, bool) or not isinstance(shift, int):
        return f"shift {shift!r} is not a whole number of rows"
    return scope, centre, shift
