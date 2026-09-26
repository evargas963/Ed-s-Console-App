"""
Layer A — authoritative in-process live quote plane (Ed Console).

Canonical quote fields per ticker are updated primarily from Schwab **streaming**
`LEVEL_ONE_EQUITY` WebSocket rows (`record_from_level_one_equity`). REST `/api/fast-quote`
remains a secondary / fallback path (`record_quote` from `_fetch_fast_quote_payload`).

Tier A `GET /api/live/state` and optional SSE `live_quote` events read this plane so
visible spot/bid/ask track the latest row. Tier B `GET /api/analytics/light` merges the
plane for live spot vs cached structure + order-flow engine input. Full analytical payloads
(`GET /api/analytics/state`, legacy `GET /api/state`, `_fetch_state`) also merge from the plane.

Layers (see server lifespan / architecture docs):
  A — Tick/quote plane (this module)
  B — Client fast mark-to-market (reads plane via HTTP + SSE live_quote)
  C — Analytical refresh (`_fetch_state`, SSE full snapshots)
  D — Persistence (DB, outcomes, training) — never on quote hot path
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from instrument_identity import ticker_storage_key

log = logging.getLogger(__name__)



_lock = threading.RLock()
# ticker UPPER -> last plane payload (streaming and/or REST fast quote)
_by_ticker: dict[str, dict[str, Any]] = {}
# ticker -> last fast_generation_id we pushed on SSE live_quote (coalesce duplicate rows)
_last_sse_pushed_gen: dict[str, float] = {}

_gen_lock = threading.Lock()
_fast_lane_gen_by_ticker: dict[str, int] = {}


def next_fast_generation(ticker: str) -> int:
    """Monotonic per-ticker generation for SSE coalescing (independent of decision_generation_id)."""
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical quote-plane key (write+read consistent; idempotent on Schwab stream symbols)
    with _gen_lock:
        n = _fast_lane_gen_by_ticker.get(t, 0) + 1
        _fast_lane_gen_by_ticker[t] = n
        return n


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        x = float(val)
    except (TypeError, ValueError):
        return None
    if x != x:  # NaN
        return None
    return x


def _positive_float(val: Any) -> Optional[float]:
    f = _safe_float(val)
    if f is None or f <= 0:
        return None
    return f


def _epoch_seconds_from_millis(val: Any) -> Optional[float]:
    f = _safe_float(val)
    if f is None or f <= 0:
        return None
    return f / 1000.0


#: Schwab LEVELONE_EQUITIES sends only the fields that CHANGED since the last message for a
#: symbol. Measured on 4,039 real captured messages (stream_quotes_raw, 2026-09-24): only 11%
#: carried bid, ask and last together; 17% were ask-only, 15% bid-only, 23% none of the three.
#: So a field absent from a message is UNCHANGED, not missing -- the current value of each
#: field is the last one Schwab sent, and its age is the age of THAT message. This table holds
#: exactly that, per ticker, per field: {field: (value, received_ts)}.
_PRICE_FIELDS = ("LAST_PRICE", "BID_PRICE", "ASK_PRICE", "MARK", "CLOSE_PRICE",
                 "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE")
_COUNT_FIELDS = ("BID_SIZE", "ASK_SIZE", "LAST_SIZE", "TOTAL_VOLUME")
_CLOCK_FIELDS = ("QUOTE_TIME_MILLIS", "TRADE_TIME_MILLIS")
#: signed values (any finite number): Schwab's own change of the LAST_PRICE vs the prior close.
#: Measured 2026-09-24: NET_CHANGE_PERCENT arrives with every LAST_PRICE (1,232 of 1,232
#: captured); REGULAR_MARKET_CHANGE_PERCENT only on full refreshes; CHANGE_PERCENT never.
_SIGNED_FIELDS = ("NET_CHANGE", "NET_CHANGE_PERCENT")
_fields_by_ticker: dict[str, dict[str, tuple[float, float]]] = {}


def _read_stream_field(name: str, raw: Any) -> Optional[float]:
    if name in _PRICE_FIELDS:
        return _positive_float(raw)
    if name in _COUNT_FIELDS:
        v = _safe_float(raw)
        return v if v is not None and v >= 0 else None
    if name in _SIGNED_FIELDS:
        return _safe_float(raw)
    return _epoch_seconds_from_millis(raw)


def record_from_level_one_equity(ticker: str, item: dict[str, Any], *,
                                 received_ts: float) -> bool:
    """
    Ingest one Schwab streaming LEVELONE_EQUITIES content item into the plane.
    Returns True when a plane row was (re)published.

    Per-field state (see _fields_by_ticker): each field present in the message replaces
    that field's value and receive time; absent fields stand (Schwab sends changes only).
    A present-but-invalid price (0 / negative -- e.g. no bid) CLEARS that field: the vendor
    said there is no such value now. A row is published once a LAST_PRICE is known; spot is
    LAST_PRICE only (MARK never stands in) and its age is the age of the last LAST_PRICE
    message, never of the bid/ask tick arriving now.

    `received_ts` is REQUIRED: the capture daemon's own receive time for this message --
    what every freshness check judges (2026-09-23 audit P0).
    """
    if not item or not isinstance(item, dict):
        return False
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical quote-plane key
    if not t:
        return False
    rts = float(received_ts)
    seen = False
    with _lock:
        fs = _fields_by_ticker.setdefault(t, {})
        for name in _PRICE_FIELDS + _COUNT_FIELDS + _CLOCK_FIELDS + _SIGNED_FIELDS:
            if name not in item:
                continue
            seen = True
            v = _read_stream_field(name, item.get(name))
            if v is None:
                fs.pop(name, None)       # vendor sent "none" (e.g. BID_PRICE 0): cleared
            else:
                fs[name] = (v, rts)
        snapshot = dict(fs)
    if not seen or "LAST_PRICE" not in snapshot:
        return False

    def val(name: str) -> Optional[float]:
        return snapshot[name][0] if name in snapshot else None

    spot_f = val("LAST_PRICE")
    bid, ask, mark = val("BID_PRICE"), val("ASK_PRICE"), val("MARK")
    quote_ts = val("QUOTE_TIME_MILLIS")   # exchange quote clock; TRADE_TIME never stands in
    spread_pts = round(ask - bid, 4) if bid is not None and ask is not None else None
    spread_frac = (ask - bid) / mark if spread_pts is not None and mark is not None else None
    out = {
        "ticker": t,
        "spot": float(spot_f),
        "bid": bid,
        "ask": ask,
        "spot_disp": f"{float(spot_f):.2f}",
        "bid_disp": f"{bid:.2f}" if bid is not None else "—",
        "ask_disp": f"{ask:.2f}" if ask is not None else "—",
        "quote_mid": mark,
        "mid_source": "schwab_streaming_mark" if mark is not None else None,
        "spread": spread_frac,
        "spread_pts": spread_pts,
        "spread_source": "derived_bid_ask_fraction_schwab_mark_denom" if spread_frac is not None else None,
        "spread_pts_source": "derived_bid_ask_pts" if spread_pts is not None else None,
        "bid_size": val("BID_SIZE"),
        "ask_size": val("ASK_SIZE"),
        "last_size": val("LAST_SIZE"),
        "total_volume": val("TOTAL_VOLUME"),
        "open_price": val("OPEN_PRICE"),
        "high_price": val("HIGH_PRICE"),
        "low_price": val("LOW_PRICE"),
        "prior_close": val("CLOSE_PRICE"),
        # Schwab's own change of LAST_PRICE vs prior close (0 hops) -- the watchlist / header %
        "chg_pct": val("NET_CHANGE_PERCENT"),
        "net_change": val("NET_CHANGE"),
        "fast_generation_id": next_fast_generation(t),
        "exchange_quote_ts": quote_ts,
        #: TRADE_TIME_MILLIS (epoch s): the exchange time of the last trade -- the clock a
        #: LAST_PRICE tick belongs to (candles); never used as the quote time.
        "trade_ts": val("TRADE_TIME_MILLIS"),
        "quote_time_source": "schwab_streaming_level_one" if quote_ts is not None else "unavailable",
        "server_received_ts": rts,
        "spot_received_ts": snapshot["LAST_PRICE"][1],
        #: each field's own receive time -- a value's age is the age of the message that set it
        "field_received_ts": {name: ts for name, (_, ts) in snapshot.items()},
        "quote_ingestion": "schwab_streaming_level_one",
        "quote_source_detail": {
            "spot": "LAST_PRICE",
            "bid": "BID_PRICE" if bid is not None else None,
            "ask": "ASK_PRICE" if ask is not None else None,
            "mid": "schwab_streaming_mark" if mark is not None else "unavailable_missing_mark",
            "spread": "schwab_bid_ask" if spread_pts is not None else "unavailable_missing_bid_or_ask",
            "quote_ts": "QUOTE_TIME_MILLIS" if quote_ts is not None else "unavailable",
        },
    }
    with _lock:
        _by_ticker[t] = out
    for fn in list(_row_listeners):
        try:
            fn(t)
        except Exception as e:  # noqa: BLE001 -- counted + WARNING; one bad listener never stops ingest
            _row_listener_failures[0] += 1
            n = _row_listener_failures[0]
            if n & (n - 1) == 0:
                log.warning("plane row listener %s failed for %s (%s failures): %s",
                            getattr(fn, "__name__", fn), t, n, e)
    return True


#: callables told the ticker of every published row, in the process that owns this plane --
#: the console registers its L1 rebuild, the capture daemon its browser push, live_price_rows
#: its forming candle. The plane itself knows no consumer (it used to import the console's
#: planes.l1_events directly, which tied the price table to the console process).
_row_listeners: list = []
_row_listener_failures = [0]


def add_row_listener(fn) -> None:
    if fn not in _row_listeners:
        _row_listeners.append(fn)


def remove_row_listener(fn) -> None:
    if fn in _row_listeners:
        _row_listeners.remove(fn)


def get_quote(ticker: str) -> Optional[dict[str, Any]]:
    """Copy of latest plane row for ticker, or None."""
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical quote-plane key (write+read consistent; idempotent on Schwab stream symbols)
    with _lock:
        row = _by_ticker.get(t)
        return dict(row) if row else None




def plane_row_is_streamed(row: dict) -> bool:
    """True only for a row the Schwab LEVELONE_EQUITIES stream wrote. Rows the REST
    refreshers write carry their own quote_ingestion tag and are NOT stream identity."""
    return (row or {}).get("quote_ingestion") == "schwab_streaming_level_one"  # caps-ok: fail-closed -- no row is not a streamed row


def plane_spot_is_last_price(row: dict[str, Any] | None) -> bool:
    """True only when this plane row's spot is a native Schwab LAST_PRICE."""
    if not row or not isinstance(row, dict):
        return False
    spot = _positive_float(row.get("spot"))
    if spot is None:
        return False
    qsd = row.get("quote_source_detail")
    if not isinstance(qsd, dict):
        return False
    return qsd.get("spot") == "LAST_PRICE"


#: The daemon pushes a heartbeat every second over the live push connection; the console
#: treats the feed as live only while the latest one is younger than this (console clock).
FEED_HEARTBEAT_MAX_AGE_SEC: float = 3.0

#: The daemon's own report of its feed, from its latest heartbeat: when the console received
#: it, whether the Schwab socket was open, and which equities the daemon holds on
#: LEVELONE_EQUITIES. Written by the push feed loop only.
_feed: dict[str, Any] = {"rx": None, "socket_open": False, "held": frozenset()}


def record_feed_heartbeat(msg: dict[str, Any], received_at: float) -> None:
    """Apply one daemon heartbeat (topic ``daemon.heartbeat``)."""
    held = (msg.get("held") or {}).get("LEVELONE_EQUITIES") if isinstance(msg, dict) else None
    with _lock:
        _feed["rx"] = float(received_at)
        _feed["socket_open"] = bool(isinstance(msg, dict) and msg.get("schwab_socket_open") is True)
        _feed["held"] = frozenset(ticker_storage_key(s) for s in held) if isinstance(held, list) else frozenset()


def record_feed_down() -> None:
    """The push connection to the daemon ended: nothing is live until a heartbeat arrives."""
    with _lock:
        _feed["rx"] = None
        _feed["socket_open"] = False
        _feed["held"] = frozenset()


def feed_live_for(ticker: str | None) -> bool:
    """Is the Schwab LEVELONE_EQUITIES feed delivering THIS symbol right now: a daemon
    heartbeat arrived within FEED_HEARTBEAT_MAX_AGE_SEC, it reported the Schwab socket open,
    and it holds the symbol's subscription.

    This is the liveness question -- not "did a field arrive recently". Schwab sends a field
    only when it CHANGES (measured: 11% of 4,039 messages carried bid+ask+last together), so
    a quiet symbol's unchanged LAST_PRICE is its current last trade, not an old value; judging
    by the field's arrival age blanked quiet names on a healthy feed (2026-09-24 08:44 CT,
    DELL) and kept a dead feed's prices "live" for 30 s."""
    t = ticker_storage_key(ticker or "")
    with _lock:
        rx, open_, held = _feed["rx"], _feed["socket_open"], _feed["held"]
    if rx is None or not open_ or not t or t not in held:
        return False
    age = time.time() - rx
    return 0.0 <= age < FEED_HEARTBEAT_MAX_AGE_SEC


def spot_is_fresh(q: dict[str, Any]) -> bool:
    """Is this row's LAST_PRICE live right now: the stream delivered a LAST_PRICE for it this
    session (`spot_received_ts`) and the feed is live for its symbol (feed_live_for). Its
    age since the last trade is information (`trade_ts`), never a reason to blank it."""
    if _safe_float((q or {}).get("spot_received_ts")) is None:  # caps-ok: fail-closed -- no LAST_PRICE this session is not live
        return False
    return feed_live_for((q or {}).get("ticker"))


def streamed_chg_pct(row: dict[str, Any] | None) -> Optional[float]:
    """THE percent change: Schwab LEVELONE_EQUITIES NET_CHANGE_PERCENT (0 hops) from a row the
    stream wrote, while its LAST_PRICE is fresh -- NET_CHANGE_PERCENT arrives with every
    LAST_PRICE (measured on 4,039 messages), so it is live exactly while the last is. Otherwise
    None: no REST value, no stale row (2026-09-24)."""
    if not (row and plane_row_is_streamed(row) and spot_is_fresh(row)):
        return None
    from numeric_contract import float_finite_or_none
    return float_finite_or_none(row.get("chg_pct"))


def quote_is_fresh(q: dict[str, Any]) -> bool:
    """Is this plane row's quote (bid/ask/sizes) live right now: the stream wrote the row
    (`server_received_ts`) and the feed is live for its symbol (feed_live_for). Under
    Schwab's changed-fields-only delivery an unchanged bid IS the current bid while the feed
    is live; a missing server_received_ts cannot be assumed live (fail closed)."""
    if _safe_float(q.get("server_received_ts")) is None:
        return False
    return feed_live_for(q.get("ticker"))








def reset_sse_push_cursor(ticker: str) -> None:
    """Force next SSE live_quote push (e.g. after ticker change)."""
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical quote-plane key (write+read consistent; idempotent on Schwab stream symbols)
    with _lock:
        _last_sse_pushed_gen.pop(t, None)
