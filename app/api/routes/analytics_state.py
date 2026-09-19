"""Tier C route layer — full analytics pipeline read/schedule entry points
(RC-REHAB-1, Phase 3). See docs/ANALYTICS_STATE_TIER_BOUNDARIES_V1.md for the full tier map.

These three routes are pure dispatchers: they never call `_fetch_state` (the ~3,400-line
compute core) inline. `_tier_c_analytics_json_response` is a stale-while-refresh cache view
that reads `_state_cache` and schedules a background recompute when stale;
`_schedule_analytics_warm`/`_schedule_analytics_recompute` are the scheduling layer that
actually submits `_fetch_state` to a background executor. All three of those, plus every
other dependency here, have callers outside this route layer (the SSE loop, the background
ticker logger, a startup warm sweep) and stay in server.py, imported back lazily -- per the
boundary doc's explicit recommendation NOT to move the read/schedule/compute core itself in
this slice.
"""

from __future__ import annotations

import asyncio

from config import DEFAULT_TICKER
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/api/analytics/state")
async def get_analytics_state(
    ticker: str = Query(default=DEFAULT_TICKER),
    symbol: str | None = Query(default=None),
    expiry: str | None = Query(default=None),
    force: bool = Query(default=False),
):
    """
    Tier C — full analytical pipeline (_fetch_state): chain, exposures, fusion, DB, news, model health.
    Not required for first paint; cache-first when TTL allows.
    """
    from server import _get_fast_quote_executor, _resolve_ticker_param, _tier_c_analytics_json_response

    t = _resolve_ticker_param(ticker, symbol)
    # SWITCH-LATENCY FIX: async route — the handler is stale-while-refresh (light), but it
    # calls _register_tracked_ticker (SQLite write) on entry, which blocks the event loop
    # during DB contention. Offload it; the heavy recompute it schedules already runs on
    # its own thread pool.
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _get_fast_quote_executor(),
        lambda: _tier_c_analytics_json_response(t, expiry, force, "rest_analytics"),
    )


@router.post("/api/analytics/warm")
async def post_analytics_warm(
    ticker: str = Query(default=DEFAULT_TICKER),
    symbol: str | None = Query(default=None),
    expiry: str | None = Query(default=None),
):
    """
    UI-MAXIMIZE — schedule Tier C background recompute + ML artifact prewarm (non-blocking).
    Client fires on ticker switch / typeahead; does not await _fetch_state completion.
    """
    from server import (
        _get_route_offload_executor,
        _resolve_ticker_param,
        _schedule_analytics_warm,
        _touch_tracked_ticker_view,
    )

    t = _resolve_ticker_param(ticker, symbol)

    def _warm():
        _touch_tracked_ticker_view(t)
        return _schedule_analytics_warm(t, expiry, "client_warm_post", prewarm_models=True)

    loop = asyncio.get_event_loop()
    payload = await loop.run_in_executor(_get_route_offload_executor(), _warm)
    return JSONResponse(payload)


@router.get("/api/state")
# SWITCH-LATENCY FIX: sync def → Starlette runs it in its worker threadpool, off the
# event loop (this handler does blocking Tier C work and no await).
def get_state(
    ticker: str = Query(default=DEFAULT_TICKER),
    symbol: str | None = Query(default=None),
    expiry: str | None = Query(default=None),
    force: bool = Query(default=False),
):
    """
    Deprecated alias for GET /api/analytics/state (Tier C full bundle).
    Prefer /api/live/state + /api/analytics/state for real-time UX.
    Query ``ticker=`` (preferred) or ``symbol=`` (alias).
    """
    from server import _resolve_ticker_param, _tier_c_analytics_json_response

    return _tier_c_analytics_json_response(
        _resolve_ticker_param(ticker, symbol), expiry, force, update_source="rest_poll_legacy"
    )
