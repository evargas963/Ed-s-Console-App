"""Tier A — instant live quote plane API routes (RC-REHAB-1, Phase 3). See
docs/ANALYTICS_STATE_TIER_BOUNDARIES_V1.md for the full tier map: these three routes read
only the live-market-plane singleton (_lmp) and streaming diagnostics -- no chain fetch, no
exposures, no DB read, no model stack, and no dependency on _fetch_state or any Tier C state.
Every shared dependency (the quote-hot executor, _touch_tracked_ticker_view,
_resolve_ticker_param, the fast-quote fallback ladder) has other callers in server.py
(including the still-unmoved Tier C routes) and stays there, imported back lazily.
"""

from __future__ import annotations

import asyncio
import threading
import time

from config import DEFAULT_TICKER
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from instrument_identity import ticker_storage_key

router = APIRouter()


@router.get("/api/live/state")
async def get_live_state(
    ticker: str = Query(default=DEFAULT_TICKER),
    symbol: str | None = Query(default=None),
    expiry: str | None = Query(default=None),
):
    """
    Tier A — instant live quote plane + session + identity. No chain, exposures, DB, news, or heavy compute.
    Primary driver for responsive UI; use GET /api/analytics/state for full analytical bundle.
    """
    from tier_a_live_state import _tier_a_live_state_dict
    from server import _get_quote_hot_executor, _resolve_ticker_param, _touch_tracked_ticker_view

    t = _resolve_ticker_param(ticker, symbol)
    # SWITCH-LATENCY FIX: this route is async, so ANY blocking work here stalls the whole
    # event loop (all SSE streams, the fast-quote poll, every other request) until it
    # returns — the root cause of slow ticker switches. Both _register_tracked_ticker
    # (persists the symbol to the SQLite logging_universe — a DB write that contends with
    # the live logger/retrain) and _tier_a_live_state_dict (blocking Schwab REST + retry on
    # a cold ticker) must run OFF the loop. Offload to the thread pool, like /api/fast-quote.
    def _build():
        # TICKER-PREVIEW-NO-ENROLL: live-state view touches last-seen only, never enrolls.
        _touch_tracked_ticker_view(t)
        return _tier_a_live_state_dict(t, expiry)
    loop = asyncio.get_event_loop()
    payload = await loop.run_in_executor(_get_quote_hot_executor(), _build)
    return JSONResponse(payload)


@router.get("/api/live/plane")
def api_live_plane(ticker: str = Query(default=DEFAULT_TICKER)):
    """Diagnostics: Layer A row + streaming health — no Schwab REST quote call."""
    from server import _lmp, log

    t = (ticker or DEFAULT_TICKER).upper().strip()
    row = _lmp.get_quote(t)
    base = dict(row) if row else {}
    try:
        from app.options.order_flow.streaming import get_streaming_diagnostics, get_plane_authority_for_ticker

        base.update(get_streaming_diagnostics())
        base["plane_quote_authority"] = get_plane_authority_for_ticker(t)
    except Exception:
        base["plane_quote_authority"] = "rest_only"
    base["streaming_fallback_explicit"] = base.get("plane_quote_authority") == "rest_fallback_explicit"
    try:
        from app.options.order_flow.state import get_stream_chg_pct, get_top_of_book_sizes

        _scp = get_stream_chg_pct(t)
        if _scp is not None:
            base["stream_chg_pct"] = _scp
        base.update(get_top_of_book_sizes(t))
    except Exception as e:
        log.warning(
            "app.options.order_flow.state merge failed for /api/state ticker=%s: %s",
            t,
            e,
            exc_info=True,
        )
    return JSONResponse(base)


@router.get("/api/fast-quote")
async def fast_quote(ticker: str = Query(default=DEFAULT_TICKER)):
    """
    Fast lane: latest equity quote fields only. Independent fast_generation_id / exchange_quote_ts.
    Does not return chain, fusion, or decision data.
    """
    from server import (
        _fast_quote_token_invalid_payload,
        _fetch_fast_quote_payload,
        _get_quote_hot_executor,
        _lmp,
        _plane_fast_quote_has_spot,
        _schwab_auth_http_unavailable,
        _stale_fast_quote_carried_forward,
        _touch_tracked_ticker_view,
        log,
    )

    ticker = ticker_storage_key(ticker)   # RC-126: SPX -> $SPX etc., ONE authority
    route_t0 = time.perf_counter()
    asyncio_thread = threading.current_thread().name
    log.info(
        "fast_quote_route_enter ticker=%s asyncio_thread=%s",
        ticker,
        asyncio_thread,
    )
    loop = asyncio.get_event_loop()
    submit_ts = time.perf_counter()
    # SWITCH-LATENCY FIX: _register_tracked_ticker persists to the SQLite logging_universe
    # (a DB write); keep it off the event loop alongside the quote fetch.
    def _reg_and_fetch():
        # TICKER-PREVIEW-NO-ENROLL: fast-quote view touches last-seen only, never enrolls.
        _touch_tracked_ticker_view(ticker)
        return _fetch_fast_quote_payload(ticker)
    try:
        payload = await loop.run_in_executor(_get_quote_hot_executor(), _reg_and_fetch)
        after_exec = time.perf_counter()
        log.info(
            "fast_quote_route_done ticker=%s asyncio_thread=%s route_total_ms=%.2f await_executor_ms=%.2f",
            ticker,
            asyncio_thread,
            (after_exec - route_t0) * 1000.0,
            (after_exec - submit_ts) * 1000.0,
        )
        return JSONResponse(payload)
    except HTTPException as he:
        if _schwab_auth_http_unavailable(he):
            stale = _lmp.get_quote(ticker)
            if _plane_fast_quote_has_spot(stale):
                return JSONResponse(_stale_fast_quote_carried_forward(stale, ticker))
            return JSONResponse(
                status_code=401,
                content=_fast_quote_token_invalid_payload(str(he.detail or "")),
            )
        if he.status_code >= 400:
            log.warning("Fast quote HTTP %s for %s: %s", he.status_code, ticker, he.detail)
        raise
    except Exception as e:
        from schwab_client import SchwabAuthError, _is_token_error

        if _is_token_error(e) or isinstance(e, SchwabAuthError):
            stale = _lmp.get_quote(ticker)
            if _plane_fast_quote_has_spot(stale):
                return JSONResponse(_stale_fast_quote_carried_forward(stale, ticker))
            return JSONResponse(
                status_code=401,
                content=_fast_quote_token_invalid_payload(str(e)),
            )
        log.error(f"Fast quote failed for {ticker}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
