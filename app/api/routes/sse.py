"""The legacy full-market-state SSE stream (RC-REHAB-1, Phase 3). Distinct from Tier A's
/api/live/state (app/api/routes/live.py) and Tier L1's /api/analytics/light/stream
(app/api/routes/analytics_light.py) -- this pushes whatever a subscriber's background Tier C
recompute cycle produces. The SSE connection registry (_sse_lock/_sse_clients/_sse_subscribers)
and _sse_conn_epoch are also read/written by server.py's own background SSE loops
(_broadcast_live_quote_sse_payloads, _sse_background_loop) and stay there, imported back
lazily.

NOTE on _sse_conn_epoch: the original handler mutated this module-level int with a bare
`global _sse_conn_epoch; _sse_conn_epoch += 1` inside its nested generator. A `global`
statement in THIS file would bind to this module's own namespace, not server's, silently
creating a disconnected counter -- so the increment here goes through the server MODULE
OBJECT directly (`import server as _server; _server._sse_conn_epoch += 1`), which reads and
writes the real attribute on the real module regardless of which file the code executing it
lives in.
"""

from __future__ import annotations

import asyncio
import json
import time

from config import DEFAULT_TICKER
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

router = APIRouter()


@router.get("/api/stream")
async def sse_stream(
    ticker: str = Query(default=DEFAULT_TICKER),
    expiry: str | None = Query(default=None),
):
    """
    Server-Sent Events stream: pushes market state snapshots whenever fresh data is available.
    Client connects with ?ticker=X&expiry=Y; server fetches that ticker periodically and pushes.
    """
    from server import _get_fast_quote_executor, _touch_tracked_ticker_view

    ticker = ticker.upper().strip()
    expiry = expiry or None
    key = (ticker, expiry)
    # TICKER-PREVIEW-NO-ENROLL: an SSE stream connect is a VIEW subscription, not a track —
    # touch last-seen only (offloaded; may do a SQLite write for an already-enrolled ticker).
    await asyncio.get_event_loop().run_in_executor(
        _get_fast_quote_executor(), _touch_tracked_ticker_view, ticker
    )

    stream_route_t0 = time.perf_counter()

    async def event_generator():
        import server as _server  # module object, not a lazy value snapshot -- see module docstring

        q = asyncio.Queue(maxsize=10)
        with _server._sse_lock:
            _server._sse_clients.append(q)
            _server._sse_subscribers[key] = _server._sse_subscribers.get(key, 0) + 1
            # T5.1: a new connection changes the audience — the epoch bump makes
            # the next cadence fanout deliver the current bundle to this client
            # even when its identity is otherwise already-broadcast.
            _server._sse_conn_epoch += 1
        # Immediate SSE comment chunk: first body bytes must not wait on q.get() (up to 30s) or
        # some proxies/clients defer visible connection until first chunk — CONNECTING sticks.
        yield ": ok\n\n"
        _server.log.info(
            "sse_stream_first_yield ticker=%s expiry=%s ms_since_route_entry=%.2f",
            ticker,
            expiry,
            (time.perf_counter() - stream_route_t0) * 1000.0,
        )
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(q.get(), timeout=30.0)
                    if (
                        isinstance(raw, tuple)
                        and len(raw) == 2
                        and raw[0] == "live_quote"
                    ):
                        yield f"event: live_quote\ndata: {json.dumps(raw[1])}\n\n"
                    else:
                        yield f"data: {json.dumps(raw)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        except (GeneratorExit, asyncio.CancelledError):
            pass
        finally:
            with _server._sse_lock:
                if q in _server._sse_clients:
                    _server._sse_clients.remove(q)
                cnt = _server._sse_subscribers.get(key, 0) - 1
                if cnt <= 0:
                    _server._sse_subscribers.pop(key, None)
                else:
                    _server._sse_subscribers[key] = cnt

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
