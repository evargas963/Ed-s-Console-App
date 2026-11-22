"""The `surface` panel: the heatmap, the strike x expiration surface the levels producer projected.

Read from State: the published levels' surface (state.level_store), the live price and the
daemon's watchlist. Whether a page has the ticker selected is the socket's, passed in by its
entry point (`requested`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, TypedDict

import live_market_plane as lmp
from calc.terrain_engine import nearest_strike
from numeric_contract import count_text, dollars_text, strike_text
from push.answers import NotAvailable, not_available
from push.spot import resolve_spot
from push.strike_rows import WindowView, expiry_unreadable, window, window_asked
from push.verdict import LevelsVerdict, terrain_cache_get
from state.level_store import (
    CallPutTotal,
    GammaSurface,
    GridCell,
    SurfaceColumn,
    SurfaceState,
)
from time_et import ET


class Coverage(TypedDict):
    """How many of the cells on screen stream (_stream_coverage), and the header's words for it.

    The cells with a contract, how many are in each stream state, and the chip: its state, its
    label and its tooltip.
    """

    cells: int
    live: int
    partial: int
    stale: int
    pending: int
    unavailable: int
    state: str
    label: str
    title: str


class StampedColumn(SurfaceColumn):
    """An expiration column as the page draws it (_stamp_columns): expired, and the front one."""

    expired: bool
    front: bool


class ShownCell(GridCell):
    """One strike's row of the window as the page draws it (_surface_view).

    The grid's row cut to the columns drawn, then whether it is the row at the price, and the
    strike and each measure's values as the screen shows them.
    """

    spot: bool
    strike_text: str
    text: dict[str, list[str | None]]


class HeatView(WindowView):
    """The heatmap's view (_surface_view): its window's, and what the header and the scale read.

    The scope asked, the coverage of the cells on screen, each measure's largest |value| drawn
    (the colour scale), and the selected expiry when the surface does not list it.
    """

    scope: str
    coverage: Coverage
    max_abs: dict[str, float | None]
    missing_expiry: str | None


class SurfacePanel(LevelsVerdict, SurfaceState):
    """The `surface` panel (gamma_surface_payload): the heatmap's window of the published grid.

    The levels' verdict, the chain's basis, the columns, strikes and cells drawn, the grid's own
    counts, stream state and revision (SurfaceState), and the view.
    """

    ticker: str
    symbol: str
    available: Literal[True]
    reason: None
    source: str
    chain_basis: str
    expirations: list[StampedColumn]
    strikes: list[float]
    cells: list[ShownCell]
    view: HeatView


class NoSurface(TypedDict):
    """The `surface` panel's answer with no live surface: why, and whether one is coming.

    `warming`: a page shows the ticker and its chain is coming (it is on the watchlist);
    `requested`: a page shows it.
    """

    ticker: str
    available: Literal[False]
    symbol: str
    source: str
    warming: bool
    requested: bool
    reason: str


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


def _stream_coverage(cells: list[ShownCell], cols: list[int], expired_only: bool) -> Coverage:
    """How many of the heatmap's `cells` (the window on screen, _surface_view) are live.

    Over the columns `cols` that can stream (an expired column's contracts never will;
    `expired_only`: every column drawn has expired). Only cells with a contract count: a strike an
    expiry does not list was never a data point, and has no stream state. Returns the counts by
    cell state, the share live rounded down (100 only when every cell is live), and the header's
    words: `state`, `label`, `title`.
    """
    counts = {"live": 0, "partial": 0, "stale": 0, "pending": 0, "unavailable": 0}
    for cell in cells:
        for j in cols:
            stream = cell["stream"][j]
            if stream is not None:
                counts[stream["state"]] += 1
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
        "live": counts["live"],
        "partial": counts["partial"],
        "stale": counts["stale"],
        "pending": counts["pending"],
        "unavailable": counts["unavailable"],
        "state": state,
        "label": label,
        "title": title,
    }


#: the heatmap's measures: GEX and DEX are a value per cell, OI and volume {call, put, total};
#: each None where not known
HEAT_MEASURES = ("gex", "dex", "oi", "volume")
#: each heatmap measure's text: GEX and DEX in dollars, open interest and volume counts
HEAT_TEXT = {"gex": dollars_text, "dex": dollars_text, "oi": count_text, "volume": count_text}


def _totals(legs: list[CallPutTotal | None]) -> list[float | None]:
    """One heatmap row's totals of a {call, put, total} measure, None where not known (_legs)."""
    return [None if cp is None else cp["total"] for cp in legs]


def _surface_view(
    surf: GammaSurface,
    exps: list[StampedColumn],
    spot_strike: float | None,
    scope: str,
    centre: float | None,
    shift: int,
    cols: int | None,
    expiry: str | None,
) -> tuple[list[StampedColumn], list[float], list[ShownCell], HeatView]:
    """Return the heatmap the page draws: its columns, its strikes, its cells and the view.

    Rows: _window.
    Columns (of `exps`, the grid's stamped): the selected `expiry` alone; else for Auto the
    nearest `cols` (as many as the page fits) that have not expired, for Wider twice that,
    expired ones after, for All every one; with none unexpired, the expired ones (drawn labelled
    EXPIRED, a past observation). Each cell: `spot` (the row at the price), its strike and each
    measure's values as the screen shows them. The view: the window's centre and note, the
    coverage, each measure's largest |value| drawn (the colour scale), and `missing_expiry` when
    the selected expiry is not in the surface.
    """
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
    cells: list[ShownCell] = []
    #: every value drawn, by measure: the colour scale reads them
    drawn: dict[str, list[float | None]] = {m: [] for m in HEAT_MEASURES}
    for cell in surf["cells"][lo : hi + 1]:
        oi = [cell["oi"][j] for j in picked]
        volume = [cell["volume"][j] for j in picked]
        # each measure's value per column: GEX and DEX as held, open interest and volume in total
        values: dict[str, list[float | None]] = {
            "gex": [cell["gex"][j] for j in picked],
            "dex": [cell["dex"][j] for j in picked],
            "oi": _totals(oi),
            "volume": _totals(volume),
        }
        for m in HEAT_MEASURES:
            drawn[m] += values[m]
        cells.append(
            {
                "strike": cell["strike"],
                "gex": values["gex"],
                "dex": values["dex"],
                "vanna": [cell["vanna"][j] for j in picked],
                "oi": oi,
                "volume": volume,
                "contracts": [cell["contracts"][j] for j in picked],
                "stream": [cell["stream"][j] for j in picked],
                "spot": cell["strike"] == spot_strike,
                # its strike and each measure's values as the screen shows them
                "strike_text": strike_text(cell["strike"]),
                "text": {m: [HEAT_TEXT[m](v) for v in values[m]] for m in HEAT_MEASURES},
            }
        )
    streams = [i for i, j in enumerate(picked) if not exps[j]["expired"]]
    max_abs: dict[str, float | None] = {}
    for m in HEAT_MEASURES:
        known = [abs(v) for v in drawn[m] if v is not None]
        max_abs[m] = max(known) if known else None
    return (
        [exps[j] for j in picked],
        surf["strikes"][lo : hi + 1],
        cells,
        {
            **view,
            "scope": scope,
            "coverage": _stream_coverage(cells, streams, bool(picked) and not streams),
            "max_abs": max_abs,
            "missing_expiry": expiry if expiry and not picked else None,
        },
    )


def _stamp_columns(columns: list[SurfaceColumn], now: datetime) -> list[StampedColumn]:
    """Stamp the grid's expiration `columns` at `now` (ET; a browser never decides what day it is).

    `expired` (its expiry is before now's date) and `front` (the nearest expiry that has not
    expired, by Schwab's daysToExpiration). No cell value is touched.
    """
    today = now.strftime("%Y-%m-%d")
    dated = [
        (e["dte"], e["expiry"]) for e in columns if e["expiry"] >= today and e["dte"] is not None
    ]
    front = min(dated, key=lambda nearest: nearest[0])[1] if dated else None
    return [
        {
            "expiry": e["expiry"],
            "dte": e["dte"],
            "expired": e["expiry"] < today,
            "front": e["expiry"] == front,
        }
        for e in columns
    ]


def gamma_surface(
    ticker: str, now: float, params: dict[str, Any], *, requested: bool
) -> SurfacePanel | NoSurface | NotAvailable:
    """Return the heatmap: the strike x expiration surface the levels producer projected.

    The `surface` panel. Cell = net_gex_1pct, compute_exposures_by_strike; cut to the window the
    page draws (_surface_view: the scope, the panned centre and a drag's shift, _window_asked;
    `cols`, the columns the page fits, a whole number from 1, or None for every column; `expiry`,
    the selected expiry, or None for all), with its `view`: the centre, the coverage words, the
    contracts to stream and the colour scale. Parameters that ask for none of these: the words
    saying which. `ticker` is the levels' own key; `requested`, whether a page has it selected.
    """
    asked = window_asked(params)
    if isinstance(asked, str):
        return not_available(ticker, asked)
    if "cols" not in params:
        return not_available(ticker, "the heatmap's window names no cols")
    cols = params["cols"]
    if cols is not None and (isinstance(cols, bool) or not isinstance(cols, int) or cols < 1):
        return not_available(ticker, f"cols {cols!r} is not a whole number of columns")
    unreadable = expiry_unreadable(params)
    if unreadable is not None:
        return not_available(ticker, unreadable)
    return gamma_surface_payload(
        ticker, *asked, cols, params["expiry"], datetime.fromtimestamp(now, ET), requested=requested
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
) -> SurfacePanel | NoSurface:
    """Return the heatmap's answer for ticker `tk` at `now` (the `surface` panel).

    With no live surface the answer is "unavailable" with the reason (_no_surface); there is no
    second source. Served with the levels' verdict (terrain_staleness), which carries the chain's
    time.
    """
    # the surface projected this cycle from the canonical live terrain wide chain
    live, verdict = terrain_cache_get(tk, now.timestamp())
    surf = None if live is None else live.gamma_surface
    if live is None or surf is None:
        return _no_surface(tk, verdict["levels_stale_reason"], now.timestamp(), requested)
    # the row at the price: the listed strike nearest the live price, the header's own rule
    spot_strike = nearest_strike(surf["strikes"], resolve_spot(tk, now=now.timestamp())[0])
    # the surface's state is the levels' (terrain_staleness: LIVE, CLOSE, STALE, NOT LIVE);
    # whether the cells on screen are streaming is the view's coverage
    columns, strikes, cells, view = _surface_view(
        surf,
        _stamp_columns(surf["expirations"], now),
        spot_strike,
        scope,
        centre,
        shift,
        cols,
        expiry,
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
        "expirations": columns,
        "strikes": strikes,
        "cells": cells,
        "contracts_total": surf["contracts_total"],
        "contracts_used": surf["contracts_used"],
        "stream_by_expiry": surf["stream_by_expiry"],
        "surface_seq": surf["surface_seq"],
        "view": view,
    }


def _no_surface(tk: str, levels_why: str | None, now: float, requested: bool) -> NoSurface:
    """Return the `surface` panel's answer with no live surface: why. Nothing stands in for it.

    `requested`: a page shows this ticker. Warming: its chain is coming, because it is on the
    watchlist (fetched in turn; while Closed, once, its close values). The reason is that state's
    own; `levels_why` is the levels' own reason for being stale (terrain_staleness), None when
    they give none.
    """
    watched = lmp.watchlist()  # the last list stands when the heartbeat is missing
    warming = watched is not None and tk in watched
    if lmp.daemon_status(now) is None:
        why = ["the capture daemon is not reporting (no current heartbeat)"]
        if watched is None:
            why.append("its watchlist is unknown")
        elif tk not in watched:
            why.append("it is not on the watchlist")
        if levels_why:
            why.append(levels_why)
    elif watched is not None and tk not in watched:
        # no chain is coming for it, at any hour: that, not how old its last levels are
        why = ["no chain is fetched for this ticker: it is not on the watchlist"]
    elif levels_why:
        why = [levels_why]
    elif warming:
        why = ["the surface is projected when the daemon delivers this ticker's chain"]
    else:
        why = ["no chain is fetched for this ticker: it is not on the watchlist"]
    return {
        "ticker": tk,
        "available": False,
        "symbol": tk,
        "source": "unavailable",
        "warming": requested and warming,
        "requested": requested,
        "reason": " — ".join(r for r in why if r),
    }
