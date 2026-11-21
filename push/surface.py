"""The `surface` panel: the heatmap, the strike x expiration surface the levels producer projected.

Read from State: the published levels' surface (state.level_store), the live price and the
daemon's watchlist. Whether a page has the ticker selected is the socket's, passed in by its
entry point (`requested`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import live_market_plane as lmp
from calc.terrain_engine import nearest_strike
from numeric_contract import count_text, dollars_text, strike_text
from push.answers import unavailable
from push.spot import resolve_spot
from push.strike_rows import window, window_asked
from push.verdict import terrain_cache_get
from time_et import ET

#: The heatmap header's chip, per coverage state: ALL STREAMING only when every cell on screen is
#: live (every visible heatmap cell is an exact option contract receiving streamed Schwab
#: updates). Never the bare word LIVE: that is the
#: price feed's word in the header.
COVERAGE_LIVE, COVERAGE_PARTIAL, COVERAGE_WARMING, COVERAGE_EXPIRED = (
    "live",
    "partial",
    "warming",
    "expired",
)


def _stream_coverage(
    cells: list[dict[str, Any]], cols: list[int], expired_only: bool
) -> dict[str, Any]:
    """How many of the heatmap's `cells` (the window on screen, _surface_view) are live.

    Over the columns `cols` that can stream (an expired column's contracts never will;
    `expired_only`: every column drawn has expired). Only cells with a contract count (a strike an
    expiry does not list was never a data point). Returns the counts by cell state, the share live
    rounded down (100 only when every cell is live), and the header's words: `state`, `label`,
    `title`.
    """
    counts = {"live": 0, "partial": 0, "stale": 0, "pending": 0, "unavailable": 0}
    for cell in cells:
        for j in cols:
            pair = cell["contracts"][j]
            if pair["call"] or pair["put"]:
                counts[cell["stream"][j]["state"]] += 1
    cells_n = sum(counts.values())
    live_pct = 100 * counts["live"] // cells_n if cells_n else None
    if not cells_n and expired_only:
        state, label, title = (
            COVERAGE_EXPIRED,
            "EXPIRED",
            "every column on screen has expired: none streams",
        )
    elif not cells_n:
        state, label, title = COVERAGE_WARMING, "WARMING", "no cell on screen has a contract yet"
    elif counts["live"] == cells_n:
        state, label, title = COVERAGE_LIVE, "ALL STREAMING", f"all {cells_n} cells streaming"
    else:
        rest = ", ".join(
            f"{n} {k.replace('_', ' ')}" for k, n in counts.items() if n and k != "live"
        )
        # the share rounded down, so it never claims more than streams; under 1% is "<1%", not 0
        state = COVERAGE_PARTIAL
        label = f"{live_pct}% STREAMING" if live_pct or not counts["live"] else "<1% STREAMING"
        title = f"{counts['live']} of {cells_n} cells streaming · {rest}"
    return {
        "cells": cells_n,
        **counts,
        "state": state,
        "label": label,
        "title": title,
    }


#: the heatmap's measures: GEX and DEX are a value per cell, OI and volume {call, put, total};
#: each None where not known
HEAT_MEASURES = ("gex", "dex", "oi", "volume")
#: each heatmap measure's text: GEX and DEX in dollars, open interest and volume counts
HEAT_TEXT = {"gex": dollars_text, "dex": dollars_text, "oi": count_text, "volume": count_text}


def _measure_values(cell: dict[str, Any], measure: str) -> list[float | None]:
    """One heatmap row's values of `measure`, a value or None per column."""
    if measure in ("oi", "volume"):  # {call, put, total}, or None where not known (_legs)
        return [cp if cp is None else cp["total"] for cp in cell[measure]]
    return list(cell[measure])


def _surface_view(
    surf: dict[str, Any],
    spot_strike: float | None,
    scope: str,
    centre: float | None,
    shift: int,
    cols: int | None,
    expiry: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the heatmap the page draws: (the surface cut to its window, the view).

    Rows: _window.
    Columns: the selected `expiry` alone; else for Auto the nearest `cols` (as many as the page
    fits) that have not expired, for Wider twice that, expired ones after, for All every one;
    with none unexpired, the expired ones (drawn labelled EXPIRED, a past observation). Each cell:
    `spot` (the row at the price). The view: the window's centre and note, the coverage,
    each measure's largest |value| drawn (the colour scale), and `missing_expiry` when the
    selected expiry is not in the surface.
    """
    exps = surf["expirations"]
    every = list(range(len(exps)))
    unexpired = [j for j in every if not exps[j]["expired"]]
    if expiry:
        picked = [j for j in every if exps[j]["expiry"] == expiry]
    elif scope == "all" or cols is None:
        picked = every
    elif scope == "wider":
        picked = sorted((unexpired + [j for j in every if j not in unexpired])[: 2 * cols])
    else:
        picked = (unexpired or every)[:cols]
    lo, hi, view = window(surf["strikes"], spot_strike, scope, centre, shift)

    def pick(v: Any) -> Any:
        return [v[j] for j in picked] if isinstance(v, list) else v

    cells: list[dict[str, Any]] = [
        {**{k: pick(v) for k, v in cell.items()}, "spot": cell["strike"] == spot_strike}
        for cell in surf["cells"][lo : hi + 1]
    ]
    for cell in cells:  # its strike and each measure's values as the screen shows them
        cell["strike_text"] = strike_text(cell["strike"])
        cell["text"] = {
            m: [HEAT_TEXT[m](v) for v in _measure_values(cell, m)] for m in HEAT_MEASURES
        }
    streams = [i for i, j in enumerate(picked) if not exps[j]["expired"]]
    max_abs: dict[str, float | None] = {}
    for m in HEAT_MEASURES:
        known = [abs(v) for cell in cells for v in _measure_values(cell, m) if v is not None]
        max_abs[m] = max(known) if known else None
    shown = {
        **surf,
        "strikes": surf["strikes"][lo : hi + 1],
        "expirations": [exps[j] for j in picked],
        "cells": cells,
    }
    return shown, {
        **view,
        "scope": scope,
        "coverage": _stream_coverage(cells, streams, bool(picked) and not streams),
        "max_abs": max_abs,
        "missing_expiry": expiry if expiry and not picked else None,
    }


def _stamp_columns(surface: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Stamp the surface's expiration columns at `now` (ET; a browser never decides what day it is).

    `expired` (its expiry is before now's date) and `front` (the nearest expiry that has not
    expired, by Schwab's daysToExpiration). No cell value is touched.
    """
    today = now.strftime("%Y-%m-%d")
    exps = [dict(e, expired=e["expiry"] < today) for e in surface["expirations"]]
    live_cols = [e for e in exps if not e["expired"] and e["dte"] is not None]
    front = min(live_cols, key=lambda e: e["dte"])["expiry"] if live_cols else None
    return {**surface, "expirations": [dict(e, front=e["expiry"] == front) for e in exps]}


def gamma_surface(
    ticker: str, now: float, params: dict[str, Any], *, requested: bool
) -> dict[str, Any]:
    """Return the heatmap: the strike x expiration surface the levels producer projected.

    The `surface` panel. Cell = net_gex_1pct, compute_exposures_by_strike; cut to the window the
    page draws (_surface_view: the scope, the panned centre and a drag's shift, _window_asked;
    `cols`, the columns the page fits, a whole number from 1, or None for every column; `expiry`,
    the selected expiry, or None for all), with its `view`: the centre, the coverage words, the
    contracts to stream and the colour scale. Parameters that ask for none of these: the words
    saying which. `ticker` is the levels' own key; `requested`, whether a page has it selected.
    """
    asked = window_asked(params)
    cols, expiry = params.get("cols"), params.get("expiry")
    if isinstance(asked, str):
        return unavailable(ticker, asked)
    if "cols" not in params or "expiry" not in params:
        return unavailable(ticker, "the heatmap's window names no cols or no expiry")
    if cols is not None and (isinstance(cols, bool) or not isinstance(cols, int) or cols < 1):
        return unavailable(ticker, f"cols {cols!r} is not a whole number of columns")
    if expiry is not None and not isinstance(expiry, str):
        return unavailable(ticker, f"expiry {expiry!r} is not an expiry date")
    return gamma_surface_payload(
        ticker, *asked, cols, expiry, datetime.fromtimestamp(now, ET), requested=requested
    )


def gamma_surface_payload(
    tk: str,
    scope: str,
    centre: float | None,
    shift: int,
    cols: int | None,
    expiry: str | None,
    now: datetime,
    *,
    requested: bool,
) -> dict[str, Any]:
    """Return the heatmap's answer for ticker `tk` at `now` (the `surface` panel).

    With no live surface the answer is "unavailable" with the reason; there is no second source.
    Served with the levels' verdict (terrain_staleness), which carries the chain's time.
    """
    # ---- LIVE: surface projected this cycle from the canonical live terrain wide chain ----
    live, verdict = terrain_cache_get(tk, now.timestamp())
    surf = None if live is None else live.gamma_surface
    _surface_live_spot = resolve_spot(tk, now=now.timestamp())
    if live is not None and surf is not None:
        spot_strike = nearest_strike(surf["strikes"], _surface_live_spot[0])
        # the surface's state is the levels' (terrain_staleness: LIVE, CLOSE, STALE, NOT LIVE);
        # whether the cells on screen are streaming is the view's coverage
        shown, view = _surface_view(
            _stamp_columns(surf, now), spot_strike, scope, centre, shift, cols, expiry
        )
        return {
            # every cell Schwab listed is drawn: a cell without a value is None, drawn "-"
            "ticker": tk,
            "symbol": tk,
            "available": True,
            "reason": None,
            "source": "terrain_live_cache",
            **verdict,
            "chain_basis": live.chain_basis,
            **shown,
            "view": view,
            # one spot on every screen: the live price, the header's own rule, after the surface's
            # own keys so its stamp cannot overwrite it.
            "spot": _surface_live_spot[0],
            "spot_source": _surface_live_spot[1],
            "spot_strike": spot_strike,
        }

    # ---- no live surface: unavailable, with the reason. Nothing stands in for it. ----
    # REQUESTED: a page shows this ticker. WARMING: its chain is coming -- it is on the
    # watchlist (fetched in turn; while Closed, once, its close values). The reason is that
    # state's own.
    _watched = lmp.watchlist()  # the last list stands when the heartbeat is missing
    _warming = _watched is not None and tk in _watched
    _levels_why = verdict["levels_stale_reason"]
    if lmp.daemon_status(now.timestamp()) is None:
        _why = ["the capture daemon is not reporting (no current heartbeat)"]
        if _watched is None:
            _why.append("its watchlist is unknown")
        elif tk not in _watched:
            _why.append("it is not on the watchlist")
        if _levels_why:
            _why.append(_levels_why)
    elif _watched is not None and tk not in _watched:
        # no chain is coming for it, at any hour: that, not how old its last levels are
        _why = ["no chain is fetched for this ticker: it is not on the watchlist"]
    elif _levels_why:
        _why = [_levels_why]
    elif _warming:
        _why = ["the surface is projected when the daemon delivers this ticker's chain"]
    else:
        _why = ["no chain is fetched for this ticker: it is not on the watchlist"]
    return unavailable(
        tk,
        " — ".join(r for r in _why if r),
        symbol=tk,
        source="unavailable",
        warming=requested and _warming,
        requested=requested,
    )
