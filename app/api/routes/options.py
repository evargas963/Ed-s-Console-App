"""Options per-strike exposure and tape API routes (RC-REHAB-1, Phase 3)."""

from __future__ import annotations

from typing import Optional

from config import DEFAULT_TICKER
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from instrument_identity import ticker_storage_key

router = APIRouter()


@router.get("/api/options/vanna-by-strike")
def get_vanna_by_strike(ticker: str = Query(default=DEFAULT_TICKER)):
    """Per-strike dealer VANNA exposure (operator field-inventory audit, 2026-09-13): the
    SAME canonical faucet (math_exposure_core.compute_exposures_by_strike) the Gamma/DEX
    heatmaps already use, aggregated across every expiry in the live wide chain (Vanna has
    no per-expiry SURFACE yet — see the Multi-Map subview's own note — so this is the
    aggregate-by-strike tier the Key Levels 'AGG $ ONLY' badge already discloses, not a
    narrower or different computation). net_vanna = call_vanna - put_vanna, the SAME
    +call/-put dealer-book convention net_gex_1pct and net_charm_daily already use (RC-211's
    exact BS-vanna faucet, math_levels.bs_vanna, independently FD-verified)."""
    from math_exposure_core import compute_exposures_by_strike as _cebs
    from numeric_contract import float_finite_or_none as _fin
    from server import _live_terrain_contracts_and_spot, _touch_tracked_ticker_view

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    _touch_tracked_ticker_view(tk)
    contracts, spot = _live_terrain_contracts_and_spot(tk)
    if not contracts:
        return JSONResponse({"ticker": tk, "available": False,
                             "reason": "no live wide chain cached yet for this ticker"})
    exposures, _diag = _cebs(contracts, spot=spot, require_oi=True)
    rows = []
    for k, b in exposures.items():
        # Independent-review finding, REPRODUCED (live SPX, 2026-09-14): call_vanna/put_vanna
        # are pre-initialized to a real 0.0 by _strike_bucket, so a strike where every contract
        # failed the OI gate returned (0.0, 0.0) here -- neither None, so the `cv is None and
        # pv is None` check never caught it and the row rendered a fabricated net_vanna of 0.0.
        # has_oi (math_exposure_core.py's own canonical signal) is the real gate.
        if not b.get("has_oi"):
            continue
        cv, pv = b.get("call_vanna"), b.get("put_vanna")
        if cv is None and pv is None:
            continue
        net = _fin(cv or 0.0) - _fin(pv or 0.0) if (_fin(cv) is not None or _fin(pv) is not None) else None
        if net is None:
            continue
        rows.append([round(float(k), 2), round(net, 2)])
    rows.sort(key=lambda r: r[0])
    return JSONResponse({
        "ticker": tk, "available": True, "spot": spot, "rows": rows,
        "method": ("live wide chain -> compute_exposures_by_strike (same faucet the Gamma/"
                   "DEX heatmaps use) -> net_vanna = call_vanna - put_vanna, aggregated "
                   "across every expiry (no per-expiry surface yet)"),
    })


@router.get("/api/options/charm-by-strike")
def get_charm_by_strike(ticker: str = Query(default=DEFAULT_TICKER)):
    """Per-strike dealer CHARM exposure (operator field-inventory audit, 2026-09-13): the
    SAME canonical faucet (math_levels.compute_charm_by_strike, the exact function
    /api/forces's charm_below/charm_above already sum) applied to the live wide chain, row-
    shaped for a strike bar chart the same way /api/terrain/strikes already is. Units:
    delta-shares decaying per day (RC-179 dealer convention: +call/-put)."""
    from math_levels import compute_charm_by_strike as _ccs
    from server import _live_terrain_contracts_and_spot, _touch_tracked_ticker_view

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    _touch_tracked_ticker_view(tk)
    contracts, spot = _live_terrain_contracts_and_spot(tk)
    if not contracts:
        return JSONResponse({"ticker": tk, "available": False,
                             "reason": "no live wide chain cached yet for this ticker"})
    per_ch = _ccs(contracts, spot)
    rows = sorted(
        [round(float(k), 2), round(float(b["net_charm"]), 4)]
        for k, b in per_ch.items() if b.get("net_charm") is not None
    )
    return JSONResponse({
        "ticker": tk, "available": bool(rows), "spot": spot, "rows": rows,
        "reason": None if rows else "charm_by_strike produced no usable strikes for this chain",
        "method": ("live wide chain -> math_levels.compute_charm_by_strike (the same faucet "
                   "/api/forces's charm_below/charm_above already sum) -> net_charm = "
                   "call_charm - put_charm per strike, delta-shares/day"),
    })


@router.get("/api/options/tape")
def get_options_tape(ticker: str = Query(default=DEFAULT_TICKER),
                     contract: Optional[str] = Query(default=None),
                     limit: int = Query(default=100)):
    """Discrete option TRADE prints (operator field-inventory audit, 2026-09-13) — the
    Options Flow tape, locked to the operator's own required schema: Time/Symbol/Expiry/
    Type/Strike/Bid x Size/Ask x Size/Trade/Size/Premium/Volume/OI/IV/Delta/provenance.
    Sourced from app.options.order_flow.history.tape_rows_for_symbol, which reads the
    ALREADY-CAPTURED native LEVELONE_OPTIONS ticks in stream_options_quotes_raw verbatim —
    no new capture, no derived/estimated field, no fabricated buy/sell aggressor side.

    `contract`, when given, scopes to exactly that vendor symbol. Otherwise scopes to every
    CURRENTLY DESIRED contract for `ticker` (the primary + additional option contracts the
    operator has actually selected — the same identity `_desired_stream_greeks_for_ticker`
    already resolves for the gamma-surface overlay), merged newest-first and capped at
    `limit` across the whole merge, not per-contract."""
    from app.options.order_flow.history import tape_rows_for_symbol
    from app.options.order_flow.streaming import (
        contract_matches_underlying,
        get_active_option_contract,
        get_active_option_contracts,
    )

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    try:
        bounded_limit = max(1, min(500, int(limit)))
    except (TypeError, ValueError):
        bounded_limit = 100

    if contract:
        symbols = [contract]
    else:
        candidates = list(get_active_option_contracts())
        primary = get_active_option_contract()
        if primary:
            candidates.append(primary)
        seen: set[str] = set()
        symbols = []
        for sym in candidates:
            if sym and sym not in seen and contract_matches_underlying(sym, tk):
                seen.add(sym)
                symbols.append(sym)

    if not symbols:
        return JSONResponse({"ticker": tk, "available": False, "rows": [],
                             "reason": "no active/additional option contract selected for this ticker"})

    rows: list[dict] = []
    for sym in symbols:
        rows.extend(tape_rows_for_symbol(sym, since_ts=0.0, limit=bounded_limit))
    rows.sort(key=lambda r: r["ts_recv"], reverse=True)
    rows = rows[:bounded_limit]
    return JSONResponse({
        "ticker": tk, "available": bool(rows), "symbols": symbols, "rows": rows,
        "reason": None if rows else "no trade prints captured yet for the selected contract(s)",
        "method": ("stream_options_quotes_raw (native LEVELONE_OPTIONS capture, already "
                   "retained) -> tape_rows_for_symbol (de-duplicated genuine trade prints, "
                   "context carried forward) -> merged newest-first across every currently "
                   "desired contract for this ticker"),
    })
