"""Tier L1 — light context plane API routes (RC-REHAB-1, Phase 3). See
docs/ANALYTICS_STATE_TIER_BOUNDARIES_V1.md for the full tier map: both routes are thin
dispatchers into the already-separate planes/ subsystem (planes.l1_events.notify_ticker_expiry_changed
and its SSE dispatch pipe) -- never into _fetch_state or any Tier C state. Every shared
dependency (the L1-light executor, the SSE reservation/release pair, the route-offload
executor, _touch_tracked_ticker_view, and the private wire-event-name helper) stays in
server.py and is imported back lazily.
"""

from __future__ import annotations

import asyncio
import json
import time

from config import DEFAULT_TICKER
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter()


@router.get("/api/analytics/light")
async def get_analytics_light(
    ticker: str = Query(default=DEFAULT_TICKER),
    expiry: str | None = Query(default=None),
    force: bool = Query(
        default=False,
        description="Explicit full L1 recompute (default: read authoritative _l1_snapshot_cache + L0 overlay).",
    ),
):
    """
    L1 context plane — reads authoritative _l1_snapshot_cache by default; full compute on cold miss,
    serve-age expiry, or force=true. Materiality-gated rebuilds run on quote/L2 hooks only.
    """
    from server import _get_l1_light_executor, _get_route_offload_executor, _touch_tracked_ticker_view, log

    t = ticker.upper().strip()
    from planes.l1_events import notify_ticker_expiry_changed

    # RC-166: L1 assembly runs on ed_l1_light (not ed_route_offload). logging_universe
    # touch is fire-and-forget on the route pool so a SQLITE wait cannot hold the L1
    # response (L1 itself is memory-only; _pipeline_ms never included that wait).
    route_t0 = time.perf_counter()
    submit_ts = time.perf_counter()
    try:
        _get_route_offload_executor().submit(_touch_tracked_ticker_view, t)
    except Exception:
        log.debug("analytics_light: touch_seen submit failed ticker=%s", t, exc_info=True)

    def _build():
        return notify_ticker_expiry_changed(t, expiry, force=force)

    loop = asyncio.get_event_loop()
    payload = await loop.run_in_executor(_get_l1_light_executor(), _build)
    after_exec = time.perf_counter()
    await_ms = (after_exec - submit_ts) * 1000.0
    total_ms = (after_exec - route_t0) * 1000.0
    log.info(
        "analytics_light_route_done ticker=%s await_executor_ms=%.2f route_total_ms=%.2f "
        "pipeline_ms=%s",
        t,
        await_ms,
        total_ms,
        (payload or {}).get("_pipeline_ms") if isinstance(payload, dict) else None,
    )
    # Shallow copy so route timing fields never mutate the authoritative L1 cache object.
    out = dict(payload) if isinstance(payload, dict) else payload
    if isinstance(out, dict):
        out["_route_await_executor_ms"] = round(await_ms, 2)
        out["_route_total_ms"] = round(total_ms, 2)
    return JSONResponse(out)


@router.get("/api/analytics/light/stream")
async def get_analytics_light_stream(
    request: Request,
    ticker: str = Query(default=DEFAULT_TICKER),
    expiry: str | None = Query(default=None),
):
    """
    Server-Sent Events for L1: pushes when _project_l1 completes for this scope (generation advances).
    Payload matches GET /api/analytics/light (uses _l1_http_get_projection — no duplicate compute path).
    """
    from server import (
        _get_route_offload_executor,
        _l1_light_sse_release,
        _l1_light_sse_try_reserve,
        _sse_event_name_for_envelope,
        _touch_tracked_ticker_view,
        log,
    )

    t = ticker.upper().strip()
    # TICKER-PREVIEW-NO-ENROLL: an L1 SSE subscription is a VIEW (chart open), not a track —
    # touch last-seen only. Fire-and-forget (RC-166): do not block SSE setup on SQLite.
    try:
        _get_route_offload_executor().submit(_touch_tracked_ticker_view, t)
    except Exception:
        log.debug("analytics_light_stream: touch_seen submit failed ticker=%s", t, exc_info=True)
    exp_key = expiry if expiry is not None else "__auto__"
    key = (t, exp_key)
    q, rs_key = _l1_light_sse_try_reserve(request, key)

    async def event_generator():
        yield ": ok\n\n"
        try:
            while True:
                try:
                    env = await asyncio.wait_for(q.get(), timeout=30.0)
                    # RC-UI-2 (independent-review finding, 2026-09-12): this connection/queue/
                    # dispatch pipe is entirely generic (see _l1_light_sse_dispatch_loop's own
                    # docstring — it scope-matches and forwards the raw env, nothing L1-specific)
                    # except the wire event name — see _sse_event_name_for_envelope.
                    yield f"event: {_sse_event_name_for_envelope(env)}\ndata: {json.dumps(env, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            _l1_light_sse_release(q, key, rs_key)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
