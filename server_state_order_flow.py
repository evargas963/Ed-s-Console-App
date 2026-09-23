"""Order-flow-data assembly phase of _fetch_state (server.py), extracted (RC-REHAB-1,
2026-09-22). Fourth real module-level slice of the _fetch_state decomposition, alongside
server_state_volatility.py, server_state_candles.py, and server_state_signals.py -- see
server_state_volatility.py's own docstring for why this decomposition exists.

_update_rest_cum_delta and its own module-level state (_rest_cum_delta/
_rest_cum_delta_session) moved here WITH _order_flow_data_for_state (its only caller,
confirmed by a repo-wide search before moving) rather than staying in server.py with a
lazy-access workaround, matching the pattern already used for db.py's SQLite cluster in
this session -- a self-contained function + its own private state moves as one unit. One
other server.py site (_fetch_state's own body) still reads _rest_cum_delta directly
(`if ms.cum_delta_proxy is None and ticker in _rest_cum_delta: ...`) without calling
_update_rest_cum_delta; server.py re-imports the dict itself (not a lazy access) for that
read, since a dict is a shared mutable object -- importing the same reference into
server.py's namespace means both modules see the same live object, no lazy indirection
needed for a plain read.

MONKEYPATCH/RUNTIME-STATE NOTE: _order_flow_data_for_state needs server's in-memory
1-minute candle accumulator (server._candles_1m), reached via the same lazy `import
server` pattern proven in server_state_volatility.py/server_state_candles.py.
_diag_on/_diag_step/_diag_done are re-imported here with the exact same try/except
fallback server.py itself uses (crash_trace is an optional diagnostic dependency, not
server.py-specific logic) rather than reached lazily -- they are cheap, stateless
diagnostic calls, not runtime singletons.
"""
from __future__ import annotations

from datetime import datetime

import logging

log = logging.getLogger(__name__)

try:
    from crash_trace import step as _diag_step, step_done as _diag_done, _on as _diag_on
except ImportError:
    _diag_on = lambda: False  # noqa: E731
    _diag_step = _diag_done = lambda n, t="": None  # noqa: E731

# In-process REST-based cum_delta accumulator (RC-REHAB-1: moved from server.py along
# with its sole updater/caller). Resets at 9:30 ET on RTH open (not midnight); pre-market
# trades do not carry into RTH.
_rest_cum_delta: dict = {}        # ticker -> running sum
_rest_cum_delta_session: str | None = None  # ET date "YYYY-MM-DD"


def _update_rest_cum_delta(ticker: str, quote: dict, now_et: datetime) -> float | None:
    """
    Update and return REST-based cum_delta accumulator for ticker.
    Resets at 9:30 ET on RTH open (not midnight). Pre-market trades do not carry into RTH.

    RC-REHAB-1 (2026-09-22, module extraction): moved from server.py into its own file,
    verbatim, along with its private module-level state -- its only caller
    (_order_flow_data_for_state) moved with it, confirmed by a repo-wide search first.
    """
    global _rest_cum_delta, _rest_cum_delta_session
    from time_et import RTH_OPEN_MINS
    from server import RTH_CLOSE_MINS, _safe_float_quote
    try:
        hour, minute = now_et.hour, now_et.minute
        mins = hour * 60 + minute
        in_rth = RTH_OPEN_MINS <= mins < RTH_CLOSE_MINS and now_et.weekday() < 5
        date_str = now_et.strftime("%Y-%m-%d")
        session_key = date_str if in_rth else f"{date_str}-premarket"
        if session_key != _rest_cum_delta_session:
            _rest_cum_delta.clear()
            _rest_cum_delta_session = session_key
    except Exception as e:
        log.debug(f"REST cum_delta session check failed: {e}")
    last_price = _safe_float_quote(quote.get("lastPrice"))
    last_size = _safe_float_quote(quote.get("lastSize"))
    bid_price = _safe_float_quote(quote.get("bidPrice"))
    ask_price = _safe_float_quote(quote.get("askPrice"))
    if last_price is None or last_size is None or last_size <= 0:
        return _rest_cum_delta.get(ticker)
    delta = 0.0
    if ask_price is not None and last_price >= ask_price:
        delta = last_size
    elif bid_price is not None and last_price <= bid_price:
        delta = -last_size
    cur = _rest_cum_delta.get(ticker)
    if cur is None:
        cur = 0.0
    _rest_cum_delta[ticker] = cur + delta
    return _rest_cum_delta[ticker]


def _order_flow_data_for_state(
    ticker: str,
    q_json: dict,
    c_json: dict,
    now_et: datetime,
) -> dict:
    """RC-REHAB-1 (Phase 4, _fetch_state decomposition, fourteenth slice): the Order Flow
    Engine input assembly phase, extracted verbatim -- builds the full Claude proxy field
    set (quote/extended/regular/fundamental/reference + chain expDateMaps + underlying +
    1m candles + optional live streaming content) and updates the REST Cum Delta
    accumulator (module-level `_rest_cum_delta`/`_rest_cum_delta_session`, referenced
    directly via _update_rest_cum_delta exactly as the original inline code did).

    Any exception building the field set is caught and logged, leaving order_flow_data at
    whatever partial state it reached (never raises); a missing
    app.options.order_flow.state module (ImportError) silently skips the live-content
    merge, exactly as the original inline nested try/except did.

    RC-REHAB-1 (2026-09-22, module extraction): moved from server.py into its own file.
    Behavior unchanged; see this module's own docstring for why it still reaches into
    server.py at call time for _candles_1m.
    """
    import server as _srv

    if _diag_on():
        _diag_step("pre_order_flow_data", ticker)
    order_flow_data: dict = {}
    try:
        q_node = q_json.get(ticker.upper()) or q_json.get(ticker) or q_json
        if isinstance(q_node, dict):
            order_flow_data["quote"] = q_node.get("quote") or {}
            order_flow_data["extended"] = q_node.get("extended") or {}
            order_flow_data["regular"] = q_node.get("regular") or {}
            order_flow_data["fundamental"] = q_node.get("fundamental") or {}
            order_flow_data["reference"] = q_node.get("reference") or {}
        else:
            order_flow_data["quote"] = {}
            order_flow_data["extended"] = {}
            order_flow_data["regular"] = {}
            order_flow_data["fundamental"] = {}
            order_flow_data["reference"] = {}
        # Reuse parsed chain JSON — second c_resp.json() reparsed the full payload every tick.
        order_flow_data["callExpDateMap"] = c_json.get("callExpDateMap") or {}
        order_flow_data["putExpDateMap"] = c_json.get("putExpDateMap") or {}
        order_flow_data["underlying"] = c_json.get("underlying") or {}
        # Order flow candles: 1m only (execution-aligned). No 5m fallback, no 5m aggregation.
        bars_1m = _srv._candles_1m.get_bars(ticker)
        order_flow_data["candles"] = [
            {
                "open": b.open, "high": b.high, "low": b.low, "close": b.close,
                # RC-REHAB-1 (2026-09-22, CAPS review during module extraction): Candle.ts
                # is a required dataclass field, never absent on a real bar from
                # _CandleAccumulator.get_bars() -- getattr(b, "ts", 0) was a dead default
                # that could only ever mask a genuine type bug by silently emitting the
                # 1970 epoch. Candle.volume IS Optional (_CandleAccumulator.tick()'s own
                # RC-168 comment: a bar with an unattributable totalVolume delta records
                # NO volume rather than a fabricated one) -- getattr(b, "volume", 0.0)
                # never actually caught that case (the attribute always exists, just
                # holds None), so a None volume was silently serialized as JSON null
                # instead of the 0.0 this order-flow-candles consumer expects; coerced
                # explicitly below instead of relying on a getattr default that couldn't
                # fire on this dataclass.
                "volume": b.volume if b.volume is not None else 0.0,
                "datetime": int(b.ts * 1000),
            }
            for b in (bars_1m or [])
        ]
        # Merge live streaming data (book + tape) if available
        try:
            if _diag_on():
                _diag_step("pre_get_content_for_symbol", ticker)
            from app.options.order_flow.state import get_content_for_symbol
            live_content = get_content_for_symbol(ticker)
            if _diag_on():
                _diag_done("get_content_for_symbol", ticker)
            if live_content:
                order_flow_data["content"] = live_content
        except ImportError:
            pass
    except Exception as _ofd_e:
        log.debug(f"Order flow data build: {_ofd_e}")

    # REST fallback: Cum Delta accumulator (polling-based) when streamer has no tape.
    # Update each poll; inject into ms after build_market_state if engine returns None.
    quote_for_cum = dict(order_flow_data.get("extended") or {})
    quote_for_cum.update(order_flow_data.get("quote") or {})
    _update_rest_cum_delta(ticker, quote_for_cum, now_et)

    return order_flow_data
