"""Quote-parse, spot, bid/ask spread, and total-volume phase of _fetch_state (server.py),
extracted (RC-REHAB-1, 2026-09-23). Thirty-second slice of the _fetch_state
decomposition -- see server_state_volatility.py's own docstring for why this
decomposition exists.

_quote_and_spread_for_state and its return type (_QuoteForState) move together, along
with the two per-ticker carry-forward dicts it alone reads and writes
(_last_spread_by_ticker / _last_spread_ts_by_ticker -- confirmed no other reader or
writer anywhere in server.py or the repo before moving).

MONKEYPATCH/RUNTIME-STATE NOTE: resolve_spot, _parse_quote_node_session_fields and
_safe_float_quote all have OTHER callers in server.py, so they stay there and are reached
through the same lazy `import server` pattern proven in prior slices (a
mock.patch.object(server, "resolve_spot", ...) keeps working unchanged).
get_stream_volume stays a lazy import from app.options.order_flow.state, exactly as it
was inline.

ORDER NOTE: the stream/chain-underlying totalVolume lookup used to run BEFORE the quote
response's status check; it now runs just after it, inside this phase. The lookup is a
read-only dict read with no side effect, so the only observable difference is that its
microseconds are attributed to _compute_ms instead of _quote_ms.
"""
from __future__ import annotations

import logging
from typing import Any, NamedTuple, Optional

from numeric_contract import float_finite_or_none

log = logging.getLogger(__name__)

# Last good bid-ask width (pts) when quote had both sides — reused if a poll drops one side
_last_spread_by_ticker: dict[str, float] = {}
_last_spread_ts_by_ticker: dict[str, float] = {}


class _QuoteForState(NamedTuple):
    session_q: dict[str, Any]
    parsed_last: Optional[float]
    parsed_mark: Optional[float]
    bid: Optional[float]
    ask: Optional[float]
    quote_time: Optional[float]
    trade_time: Optional[float]
    spot: Optional[float]
    spread_pts: Optional[float]
    spread_frac: Optional[float]
    spread_source: str
    spread_frac_source: Optional[str]
    spread_age_ms: Optional[int]
    total_vol: Optional[float]

    def quote_source_detail(self, *, spot_label: str) -> dict[str, Any]:
        """The quote_source_detail block every _fetch_state payload publishes."""
        return {
            "spot": spot_label,
            "bid": "bidPrice" if self.bid is not None else "unavailable_missing_bid",
            "ask": "askPrice" if self.ask is not None else "unavailable_missing_ask",
            "spread": self.spread_source,
            "spread_age_ms": self.spread_age_ms,
            "carried_forward": self.spread_source == "cached_last_valid_not_tradeable",
        }


def _total_volume_from_stream_or_chain(ticker: str, c_json: dict) -> Optional[float]:
    """totalVolume: WebSocket TOTAL_VOLUME preferred; else chain underlying."""
    import server as _srv

    try:
        from app.options.order_flow.state import get_stream_volume
        _stream_vol = get_stream_volume(ticker)
        if _stream_vol is not None:
            return _stream_vol
    except (ImportError, AttributeError):
        pass
    _chain_underlying = c_json.get("underlying") or {}
    if isinstance(_chain_underlying, dict):
        return _srv._safe_float_quote(_chain_underlying.get("totalVolume"))
    return None


def _total_volume_from_quote(ticker: str, node_q: Any, q_json: Any) -> Optional[float]:
    """Remaining volume fields from quote REST if stream + chain underlying had none."""
    import server as _srv

    _quote_node = node_q if isinstance(node_q, dict) else {}
    if not (_quote_node.get("quote") or _quote_node.get("extended")):
        _quote_node = q_json.get(ticker.upper()) or q_json.get(ticker) or {}
        if not isinstance(_quote_node, dict):
            if isinstance(q_json, list):
                for item in q_json:
                    if isinstance(item, dict) and (item.get("symbol") or item.get("key") or "").upper() == ticker.upper():
                        _quote_node = item
                        break
            else:
                _quote_node = {}
        if not _quote_node and isinstance(q_json, dict) and (q_json.get("quote") or q_json.get("regular")):
            _quote_node = q_json
    _quote_dict = _quote_node.get("quote") or {} if isinstance(_quote_node, dict) else {}
    _extended = _quote_node.get("extended") or {} if isinstance(_quote_node, dict) else {}
    return (
        _srv._safe_float_quote(_quote_dict.get("totalVolume"))
        or _srv._safe_float_quote(_extended.get("totalVolume"))
    )


def _quote_and_spread_for_state(
    ticker: str, c_json: dict, q_json: Any, quote_wall_ts: float,
) -> _QuoteForState:
    import server as _srv

    _total_vol = _total_volume_from_stream_or_chain(ticker, c_json)

    _node_q = q_json.get(ticker.upper()) or q_json.get(ticker) or {}
    _session_q = _srv._parse_quote_node_session_fields(_node_q)
    parsed_mark = _session_q["mark"]
    bid = _session_q["bid"]
    ask = _session_q["ask"]
    # SINGLE SPOT AUTHORITY (RC-14): route the analytics-card spot through resolve_spot,
    # reusing the quote node already fetched above (no extra round-trip). It now carries the
    # same value + precedence as /api/spot and the terrain card, and gains the stored-trade
    # fallback this path lacked (an empty live quote used to yield None / a bare mark here).
    spot, _spot_source, _spot_ts = _srv.resolve_spot(ticker, quote_node=_node_q, chain_json=None)

    # bid/ask arrive already finite-or-None from _parse_quote_node_session_fields
    # (numeric_contract.float_finite_or_none) -- no re-coercion.
    _spread_pts = round(ask - bid, 4) if (bid is not None and ask is not None) else None
    # single source: finite mark (the bare `> 0` gate let +inf through -> inf mid -> inf spread_frac)
    _pm = float_finite_or_none(parsed_mark)
    _mid_for_spread = _pm if (_pm is not None and _pm > 0) else None
    _spread_frac = (
        round(_spread_pts / _mid_for_spread, 6)
        if _spread_pts is not None and _mid_for_spread is not None
        else None
    )
    _spread_source = "unavailable_missing_bid_or_ask"
    _spread_age_ms: Optional[int] = None
    if _spread_pts is not None:
        _spread_source = "schwab_bid_ask_live"
        _spread_age_ms = 0  # observed on this very quote
        _last_spread_by_ticker[ticker] = _spread_pts
        _last_spread_ts_by_ticker[ticker] = quote_wall_ts
    elif ticker in _last_spread_by_ticker and ticker in _last_spread_ts_by_ticker:
        _spread_source = "cached_last_valid_not_tradeable"
        _spread_age_ms = max(0, int((quote_wall_ts - _last_spread_ts_by_ticker[ticker]) * 1000))

    if _total_vol is None:
        _total_vol = _total_volume_from_quote(ticker, _node_q, q_json)

    return _QuoteForState(
        session_q=_session_q,
        parsed_last=_session_q["last"],
        parsed_mark=parsed_mark,
        bid=bid,
        ask=ask,
        quote_time=_session_q["quote_time"],
        trade_time=_session_q["trade_time"],
        spot=spot,
        spread_pts=_spread_pts,
        spread_frac=_spread_frac,
        spread_source=_spread_source,
        spread_frac_source=(
            "derived_bid_ask_fraction_schwab_mark_denom" if _spread_frac is not None else None
        ),
        spread_age_ms=_spread_age_ms,
        total_vol=_total_vol,
    )
