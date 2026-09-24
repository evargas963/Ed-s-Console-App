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


#: Operator-reproduced defect (2026-09-14, spot 360 audit): merge_into_state and
#: apply_l1_live_quote_overlay below both overlaid this plane's spot/bid/ask onto an
#: already-built analytical payload UNCONDITIONALLY, with no check on the row's own age --
#: so a stalled streaming websocket kept clobbering a freshly, correctly resolve_spot()'d
#: Tier C/L1 spot with an arbitrarily old plane value, every single build, forever. This is
#: the ONE freshness boundary every plane consumer (this module's own overlays, and
#: server.py's resolve_spot / _tier_a_live_state_dict) shares, so "how stale is too stale
#: for this plane" can never again be answered three different ways in three files.
PLANE_QUOTE_STALE_SEC: float = 30.0


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
    held = msg.get("equities_held") if isinstance(msg, dict) else None
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


def merge_into_state(ms_dict: dict[str, Any], ticker: str) -> None:
    """
    Tier C only: overlay spot/bid/ask/display fields from the live plane onto an analytical ms_dict.
    Call at end of _fetch_state before return so Layer C payloads carry Layer A truth.

    Does not write to Layer A storage (_by_ticker). For L1 read-path overlay, use
    apply_l1_live_quote_overlay (same field merge, explicit L1 contract).

    A row whose feed is not live (feed_live_for) is treated exactly like no row: the caller's own
    already-computed spot (resolve_spot's, per _fetch_state's own "SINGLE SPOT AUTHORITY"
    comment immediately before this is called) stands untouched, rather than being clobbered
    by a stalled stream's last tick every single build.
    """
    q = get_quote(ticker)
    if not q:
        return
    # PRICE fields only are freshness-gated: a stale row must not clobber _fetch_state's own
    # resolve_spot-derived spot/bid/ask. chg_pct/exchange_quote_ts/fast_generation_id keep
    # their PRE-EXISTING unconditional-overwrite contract below unchanged — that guarantee
    # (a genuinely-absent percent-change must overwrite a stale one, never leave it standing)
    # is a different, already-correct property this fix does not touch.
    fresh = quote_is_fresh(q)
    # spot rides only while its OWN LAST_PRICE is fresh (spot_is_fresh), not merely the row
    last_price_spot = plane_spot_is_last_price(q) and spot_is_fresh(q)
    # Provenance always travels, even on a stale or non-LAST_PRICE row — the
    # flags are how a consumer knows not to treat the number as live.
    if "quote_source_detail" in q and q["quote_source_detail"] is not None:
        ms_dict["quote_source_detail"] = q["quote_source_detail"]
    if fresh:
        overlay_keys = [
            "bid",
            "ask",
            "bid_disp",
            "ask_disp",
            "quote_mid",
            "mid_source",
            "spread",
            "spread_pts",
            "spread_source",
            "spread_pts_source",
            "quote_ingestion",
        ]
        if last_price_spot:
            overlay_keys = ["spot", "spot_disp", *overlay_keys]
        for k in overlay_keys:
            if k in q and q[k] is not None:
                ms_dict[k] = q[k]
    # chg_pct is deliberately OUTSIDE the sparse-overlay loop above: that loop only ever
    # fills gaps (skips None), so a ticker whose percent-change genuinely went unavailable
    # on the latest fetch would leave a STALE number sitting in ms_dict forever. record_quote
    # replaces the whole plane row per fetch (never a merge), so "chg_pct" in q reflects the
    # newest attempt's real verdict, including an honest None — overwrite unconditionally.
    if "chg_pct" in q:
        ms_dict["chg_pct"] = q["chg_pct"]
    fts = q.get("exchange_quote_ts")
    if fts is not None:
        ms_dict["_live_plane_fast_ts"] = fts
        ms_dict["exchange_quote_ts"] = fts
    fg = q.get("fast_generation_id")
    if fg is not None:
        ms_dict["fast_generation_id"] = fg
    # Claiming the plane as authority when its PRICE fields were just withheld for staleness
    # would misattribute whatever spot ms_dict actually stands on (resolve_spot's, untouched
    # above) to this plane instead.
    if fresh and last_price_spot:
        ms_dict["_quote_authority"] = "live_market_plane"


def apply_l1_live_quote_overlay(l1_payload: dict[str, Any], ticker: str) -> None:
    """
    L1 only: merge current Layer A quote fields onto an L1 snapshot dict for HTTP cache reads.

    Part of server-side Tier B full_overlay assembly (Issue 28): invoked from server._l1_http_get_projection
    on cache hits — same path feeds GET /api/analytics/light and SSE payload; the client does not re-apply
    this overlay to Tier B semantics.

    Reads from _by_ticker via get_quote; never writes Layer A storage. Layer A remains pure
    quote rows — L1 semantics (structural, OF, merge metadata) never flow into _by_ticker.

    A row whose feed is not live (feed_live_for) is treated exactly like no row: the cached L1
    snapshot's own spot (already corrected at build time — see _project_l1) stands untouched
    rather than being overwritten by a stalled stream's last tick on every cache-hit read.
    """
    q = get_quote(ticker)
    if not q:
        return
    # Same split as merge_into_state: PRICE fields are freshness-gated (the cached snapshot's
    # own already-correct spot, set at build time by _project_l1, stands untouched), chg_pct
    # keeps its pre-existing unconditional-overwrite contract below unchanged.
    fresh = quote_is_fresh(q)
    # spot rides only while its OWN LAST_PRICE is fresh (spot_is_fresh), not merely the row
    last_price_spot = plane_spot_is_last_price(q) and spot_is_fresh(q)
    if "quote_source_detail" in q and q["quote_source_detail"] is not None:
        l1_payload["quote_source_detail"] = q["quote_source_detail"]
    if fresh:
        overlay_keys = [
            "bid",
            "ask",
            "bid_disp",
            "ask_disp",
            "quote_mid",
            "mid_source",
            "spread",
            "spread_pts",
            "spread_source",
            "spread_pts_source",
            "quote_ingestion",
        ]
        if last_price_spot:
            overlay_keys = ["spot", "spot_disp", *overlay_keys]
        for k in overlay_keys:
            if k in q and q[k] is not None:
                l1_payload[k] = q[k]
    # chg_pct OUTSIDE the loop, unconditional overwrite when present — see merge_into_state's
    # comment. This is the path that most needed it: an L1 payload can be served from cache
    # across many HTTP/SSE reads before the next rebuild, so a sparse (None-skipping) overlay
    # here would let a stale percentage from the PREVIOUS build survive an interim fetch that
    # genuinely came back without one — a truthfulness gap the sparse loop cannot close.
    if "chg_pct" in q:
        l1_payload["chg_pct"] = q["chg_pct"]
    fts = q.get("exchange_quote_ts")
    if fts is not None:
        l1_payload["_live_plane_fast_ts"] = fts
    if fresh and last_price_spot:
        l1_payload["_quote_authority"] = "live_market_plane"
        l1_payload["l1_live_overlay_applied"] = True


def take_fresh_sse_quote_payload(ticker: str) -> Optional[dict[str, Any]]:
    """
    If the plane has a quote row not yet sent on SSE for this ticker (by fast_generation_id),
    return a payload for event: live_quote. Otherwise None.
    """
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical quote-plane key (write+read consistent; idempotent on Schwab stream symbols)
    with _lock:
        row = _by_ticker.get(t)
        if not row:
            return None
        fg = row.get("fast_generation_id")
        if fg is None:
            return None
        prev = _last_sse_pushed_gen.get(t)
        if prev is not None and fg == prev:
            return None
        _last_sse_pushed_gen[t] = float(fg)
    out = dict(row)
    out["_plane_layer"] = "tick"
    out["_update_source"] = "live_plane_sse"
    return out


def reset_sse_push_cursor(ticker: str) -> None:
    """Force next SSE live_quote push (e.g. after ticker change)."""
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical quote-plane key (write+read consistent; idempotent on Schwab stream symbols)
    with _lock:
        _last_sse_pushed_gen.pop(t, None)
