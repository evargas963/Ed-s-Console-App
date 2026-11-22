"""The per-strike bar panels: Vanna and Charm, each strike's value at the expiry chosen."""

from __future__ import annotations

from typing import Any, Literal

from calc.terrain_engine import nearest_strike
from push.answers import NotAvailable, not_available
from push.spot import resolve_spot
from push.strike_rows import (
    BarView,
    ServedValue,
    expiry_unreadable,
    rows_of,
    served,
    window_asked,
    windowed,
)
from push.verdict import LevelsVerdict, terrain_cache_get

#: a per-strike bar panel's rows in the published levels' per-strike view
type BarKey = Literal["vanna", "charm"]

#: each per-strike bar panel's published rows and how they are made
STRIKE_BAR_METHODS: dict[BarKey, str] = {
    "vanna": "the published levels' exposure book -> call_vanna - put_vanna",
    "charm": "the published levels' charm map -> call_charm - put_charm",
}


class StrikeBarPanel(LevelsVerdict):
    """A per-strike bar panel (strike_bar_payload): Vanna or Charm at the expiry chosen.

    The levels' verdict (the rows are the published levels': their state, time, age and why), the
    window's rows as the page draws them with the window's view and scope, whether there is a bar
    to draw and why not, and how the rows are made.
    """

    ticker: str
    available: bool
    expiry: str | None
    rows: list[ServedValue]
    view: BarView
    scope: str
    reason: str | None
    method: str


def strike_bar_payload(
    tk: str,
    key: BarKey,
    scope: str,
    centre: float | None,
    shift: int,
    expiry: str | None,
    now: float,
) -> StrikeBarPanel | NotAvailable:
    """Return a per-strike bar panel's answer at `now` (vanna, charm) of `expiry`.

    The published rows `key` of `expiry` (None: every expiry's, the whole book), windowed for the
    panel (windowed), each as the page draws it (served: delta-shares, compact, the row at the
    live price marked), with the levels' verdict at `now` (terrain_cache_get: the one every
    screen shows). An expiry the published chain does not list is answered with why, never
    another expiry's rows.
    """
    method = STRIKE_BAR_METHODS[key]
    levels, verdict = terrain_cache_get(tk, now)
    if levels is None:
        return not_available(tk, "no levels published for this ticker yet")
    book = rows_of(levels.snap.per_strike, expiry)
    if book is None:
        return not_available(tk, f"the chain lists no contracts for {expiry}")
    rows = book[key]
    spot_strike = nearest_strike([r.strike for r in rows], resolve_spot(tk, now=now)[0])
    win, view = windowed(rows, spot_strike, scope, centre, shift)
    return {
        "ticker": tk,
        "available": bool(rows),
        "expiry": expiry,
        **verdict,
        "rows": [served(r, key, {"spot": spot_strike}) for r in win],
        "view": view,
        "scope": scope,
        "reason": None if rows else "no usable strikes for this chain",
        "method": method,
    }


def strike_bars(
    key: BarKey, tk: str, now: float, params: dict[str, Any]
) -> StrikeBarPanel | NotAvailable:
    """Return the per-strike bar panel `key` of `tk` at `now` in the window `params` ask for.

    "vanna": net_vanna = call_vanna - put_vanna per strike (the Vanna panel). "charm": the charm
    walls' own map, net_charm = call_charm - put_charm per strike, delta-shares/day (the Charm
    panel). Each of the expiry the page chose (`expiry`: an expiry date, or None for every
    expiry).
    """
    asked = window_asked(params)
    if isinstance(asked, str):
        return not_available(tk, asked)
    unreadable = expiry_unreadable(params)
    if unreadable is not None:
        return not_available(tk, unreadable)
    return strike_bar_payload(tk, key, *asked, params["expiry"], now)
