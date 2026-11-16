"""The per-strike bar panels: Vanna and Charm, each strike's published value in the asked window."""

from __future__ import annotations

from typing import Any

from push.answers import unavailable
from push.spot import resolve_spot
from push.strike_rows import served, window_asked, windowed
from state.level_store import published_levels
from terrain_engine import nearest_strike

#: each per-strike bar panel's published rows and how they are made
STRIKE_BAR_METHODS = {
    "vanna_rows": "the published levels' exposure book -> call_vanna - put_vanna",
    "charm_rows": "the published levels' charm map -> call_charm - put_charm",
}


def strike_bar_payload(
    tk: str, key: str, scope: str, centre: float | None, shift: int, now: float
) -> dict[str, Any]:
    """Return a per-strike bar panel's answer at `now` (vanna, charm).

    The published rows `key`, windowed for the panel (windowed), each as the page draws it
    (served: delta-shares, compact), with the live price and the strike nearest it.
    """
    method = STRIKE_BAR_METHODS[key]
    levels = published_levels(tk)
    if levels is None:
        return unavailable(tk, "no levels published for this ticker yet")
    rows = levels.vanna_rows if key == "vanna_rows" else levels.charm_rows
    spot = resolve_spot(tk, now=now)[0]
    spot_strike = nearest_strike([r.strike for r in rows], spot)
    win, view = windowed(rows, spot_strike, scope, centre, shift)
    return {
        "ticker": tk,
        "available": bool(rows),
        "spot": spot,
        "spot_strike": spot_strike,
        "rows": [served(r, key) for r in win],
        "view": view,
        "scope": scope,
        "reason": None if rows else "no usable strikes for this chain",
        "method": method,
    }


def strike_bars(key: str, tk: str, now: float, params: dict[str, Any]) -> dict[str, Any]:
    """Return the per-strike bar panel `key` of `tk` at `now` in the window `params` ask for.

    "vanna_rows": net_vanna = call_vanna - put_vanna per strike, across every expiry (the Vanna
    panel). "charm_rows": the charm walls' own map, net_charm = call_charm - put_charm per strike,
    delta-shares/day (the Charm panel).
    """
    asked = window_asked(params)
    if isinstance(asked, str):
        return unavailable(tk, asked)
    return strike_bar_payload(tk, key, *asked, now)
