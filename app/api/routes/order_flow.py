"""/api/order-flow/* API routes: book heatmap, equity + option-contract microstructure
(RC-REHAB-1, Phase 3). Every handler is a thin serializer over
app/options/order_flow/{engine,history,state,streaming}.py -- no book/imbalance math of
its own. _touch_tracked_ticker_view and _lmp (the live-market-plane singleton) have other
callers in server.py and stay there, imported back lazily.
"""

from __future__ import annotations

from config import DEFAULT_TICKER
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from instrument_identity import ticker_storage_key

router = APIRouter()


@router.get("/api/order-flow/book-heatmap")
def get_order_flow_book_heatmap(ticker: str = Query(default=DEFAULT_TICKER),
                                minutes: float = Query(default=60.0)):
    """Historical book-depth heatmap for the underlying ticker's own NASDAQ/NYSE book (operator
    field-inventory audit, 2026-09-13: "we don't have an order flow heatmap"). SERIALIZER, not a
    second producer: delegates entirely to app.options.order_flow.history.book_heatmap_for_ticker,
    which bins the SAME persisted stream_book_raw rows the live /api/order-flow/microstructure
    ladder already reads into a time x price grid. Genuinely historical (a real time axis), which
    the live ladder's one-snapshot view cannot show. The window always ends at the latest row
    actually captured for this ticker, never wall-clock now — see that function's own docstring
    for why. `minutes` is clamped to [5, 240] to bound one request's cost."""
    from app.options.order_flow.history import book_heatmap_for_ticker

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    try:
        bounded_minutes = max(5.0, min(240.0, float(minutes)))
    except (TypeError, ValueError):
        bounded_minutes = 60.0
    payload = book_heatmap_for_ticker(tk, minutes=bounded_minutes)
    return JSONResponse(payload)


@router.get("/api/order-flow/microstructure")
def api_order_flow_microstructure(ticker: str = Query(default=DEFAULT_TICKER)):
    """Canonical L2 book microstructure (ORDER_FLOW_MARKET_MICROSTRUCTURE_V1): top-of-book,
    spread, microprice, Top 1/3/5 depth totals + imbalance, depth-pressure curve, book slope,
    liquidity concentration, wall_candidates, and ages — every field classified
    NATIVE/DERIVED/PROXY. SERIALIZER, not a second producer: it delegates to the ONE canonical
    app.options.order_flow.engine.compute_book_microstructure keyed by this ticker, which carries the
    engine's already-computed structural state for the current book (memoized per ticker +
    BOOK_TIME) rather than re-walking the raw book. No Schwab REST quote call; the client
    renders, never recomputes."""
    from server import _lmp, _touch_tracked_ticker_view, log

    t = (ticker or DEFAULT_TICKER).upper().strip()
    # VIEW endpoint: touch last-seen only, never enroll (RC-160 ticker-scope discipline).
    _touch_tracked_ticker_view(t)
    data: dict = {}
    try:
        from app.options.order_flow.state import get_content_for_symbol
        _content = get_content_for_symbol(t)
        if _content:
            data["content"] = _content
    except Exception as e:  # streaming state optional — fail closed to 'no_book', never fabricate
        log.debug("microstructure content build failed for %s: %s", t, e)
    _row = _lmp.get_quote(t)
    if _row and _row.get("exchange_quote_ts") is not None:
        data["exchange_quote_ts"] = _row.get("exchange_quote_ts")
    from app.options.order_flow.engine import compute_book_microstructure
    # ticker=t → serialize the canonical state carried per (ticker, BOOK_TIME); no independent recompute.
    payload = compute_book_microstructure(data, ticker=t)
    payload["ticker"] = t
    return JSONResponse(payload)


@router.get("/api/order-flow/options-microstructure")
def api_order_flow_options_microstructure(contract: str = Query(...)):
    """Same canonical L2 book microstructure as /api/order-flow/microstructure, for one
    OPTION CONTRACT's live book. SERIALIZER, not a second producer: delegates to
    app.options.order_flow.streaming.get_option_contract_book_microstructure, which delegates
    to the SAME app.options.order_flow.engine.compute_book_microstructure the equity route reads — no
    parallel book-imbalance computation for options. `contract` MUST be a chain response's
    own "symbol" field (OSI format, e.g. "SPY   260820C00767000"); this route does not
    construct or validate that format, it only serializes whatever content has been
    replayed for the literal string given. No ticker-roster touch here — a contract symbol
    is not a ticker and does not participate in that enrollment concept."""
    c = (contract or "").strip()
    if not c:
        return JSONResponse({"error": "contract is required"}, status_code=400)
    from app.options.order_flow.streaming import (
        get_option_contract_book_microstructure,
        get_option_contract_streaming_diagnostics,
    )
    payload = get_option_contract_book_microstructure(c)
    payload["contract"] = c
    try:
        # PR214 merge blocker 1A: the diagnostics are bound to the CONTRACT BEING
        # QUERIED, not to whatever contract the plane happens to be streaming. Without
        # `c` this attached the globally-active contract's health verbatim to a book
        # computed for a different contract, so a response could read `contract: A`
        # beside `streaming_healthy: true` that belonged entirely to B. The book above
        # is still served truthfully (replayed content for A is real and is not
        # discarded); only the LIVE HEALTH claim is bound and fails closed on mismatch.
        payload["streaming_plane"] = get_option_contract_streaming_diagnostics(for_contract=c)
    except Exception:  # diagnostics are informational only — never fail the book payload for them
        payload["streaming_plane"] = {}
    return JSONResponse(payload)
