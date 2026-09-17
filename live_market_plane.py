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


def _plane_tuple_sig(spot: Any, bid: Any, ask: Any) -> tuple[Optional[float], Optional[float], Optional[float]]:
    return (
        round(spot, 6) if spot is not None else None,
        round(bid, 6) if bid is not None else None,
        round(ask, 6) if ask is not None else None,
    )


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


def record_from_level_one_equity(ticker: str, item: dict[str, Any]) -> bool:
    """
    Ingest one Schwab streaming LEVEL_ONE_EQUITY content row into the plane.
    Returns True if the stored row changed (new generation recorded).
    """
    if not item or not isinstance(item, dict):
        return False
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical quote-plane key (write+read consistent; idempotent on Schwab stream symbols)
    if not t:
        return False

    last = _positive_float(item.get("LAST_PRICE"))
    mark = _positive_float(item.get("MARK"))
    bid = _positive_float(item.get("BID_PRICE"))
    ask = _positive_float(item.get("ASK_PRICE"))

    with _lock:
        prev = _by_ticker.get(t)
        pspot = prev.get("spot") if prev else None
        pbid = prev.get("bid") if prev else None
        pask = prev.get("ask") if prev else None
        prev_spot_source = None
        if prev:
            _prev_qsd = prev.get("quote_source_detail")
            if isinstance(_prev_qsd, dict):
                prev_spot_source = _prev_qsd.get("spot")

    # Current live spot is LAST_PRICE only. MARK is the vendor mid and may update
    # quote_mid; it must never become spot. A bid/ask-only tick keeps the prior
    # LAST_PRICE rather than inventing a substitute.
    if last is not None:
        spot_f = last
        spot_source = "LAST_PRICE"
    elif (
        prev is not None
        and pspot is not None
        and pspot > 0
        and prev_spot_source == "LAST_PRICE"
    ):
        spot_f = pspot
        spot_source = "LAST_PRICE"
    else:
        return False
    bid_source = "BID_PRICE" if bid is not None else None
    ask_source = "ASK_PRICE" if ask is not None else None

    # exchange_quote_ts (set below) carries the EXCHANGE quote clock — Schwab
    # QUOTE_TIME_MILLIS in epoch seconds — NOT a server clock. The genuine server wall
    # clock is the separate server_received_ts (time.time()). When QUOTE_TIME_MILLIS is
    # absent we fall back to TRADE_TIME_MILLIS as a LABELED PROXY (M6) rather than
    # conflating the two silently; the clock actually used is recorded in
    # quote_source_detail["quote_ts"] so a trade-time value is never aged as a quote time
    # without provenance. The name->value contract (exchange_quote_ts must never hold a
    # server wall clock) is machine-pinned by tools/check_schwab_market_field_semantics (M5).
    _qtm = _epoch_seconds_from_millis(item.get("QUOTE_TIME_MILLIS"))
    _ttm = _epoch_seconds_from_millis(item.get("TRADE_TIME_MILLIS"))
    if _qtm is not None:
        quote_ts = _qtm
        quote_ts_clock = "QUOTE_TIME_MILLIS"
    elif _ttm is not None:
        quote_ts = _ttm
        quote_ts_clock = "TRADE_TIME_MILLIS_proxy"
    else:
        quote_ts = None
        quote_ts_clock = "unavailable"
    new_sig = _plane_tuple_sig(spot_f, bid, ask)
    prev_sig = _plane_tuple_sig(pspot, pbid, pask) if prev else None
    prev_quote_ts = (prev or {}).get("exchange_quote_ts")
    if (
        prev_sig == new_sig
        and (prev or {}).get("quote_ingestion") == "schwab_streaming_level_one"
        and (quote_ts is None or prev_quote_ts == quote_ts)
    ):
        return False

    spread_frac = None
    quote_mid = None
    mid_source = None
    try:
        if mark is not None:
            mark_f = float(mark)
            if mark_f > 0:
                quote_mid = mark_f
                mid_source = "schwab_streaming_mark"
        if quote_mid is not None and bid is not None and ask is not None:
            bf, af = float(bid), float(ask)
            spread_frac = (af - bf) / quote_mid
    except (TypeError, ValueError):
        pass

    server_received_ts = time.time()
    out = {
        "ticker": t,
        "spot": float(spot_f),
        "bid": float(bid) if bid is not None else None,
        "ask": float(ask) if ask is not None else None,
        "spot_disp": f"{float(spot_f):.2f}",
        "bid_disp": f"{float(bid):.2f}" if bid is not None else "—",
        "ask_disp": f"{float(ask):.2f}" if ask is not None else "—",
        "quote_mid": quote_mid,
        "mid_source": mid_source,
        "spread": spread_frac,
        "spread_pts": round(float(ask) - float(bid), 4) if bid is not None and ask is not None else None,
        "spread_source": (
            "derived_bid_ask_mid_fraction"
            if spread_frac is not None and mid_source == "derived_bid_ask_mid"
            else (
                "derived_bid_ask_fraction_schwab_mark_denom"
                if spread_frac is not None and mid_source == "schwab_streaming_mark"
                else None
            )
        ),
        "spread_pts_source": (
            "derived_bid_ask_pts" if bid is not None and ask is not None else None
        ),
        "fast_generation_id": next_fast_generation(t),
        "exchange_quote_ts": quote_ts,
        "quote_time_source": "schwab_streaming_level_one" if quote_ts is not None else "unavailable",
        "server_received_ts": server_received_ts,
        "quote_ingestion": "schwab_streaming_level_one",
        "quote_source_detail": {
            "spot": spot_source,
            "bid": bid_source,
            "ask": ask_source,
            "mid": mid_source or "unavailable_missing_mark_and_bid_ask",
            "spread": "schwab_bid_ask" if bid is not None and ask is not None else "unavailable_missing_bid_or_ask",
            "quote_ts": quote_ts_clock,  # M6: which exchange clock exchange_quote_ts carries (QUOTE_TIME_MILLIS, or TRADE_TIME_MILLIS_proxy on fallback)
            "carried_forward": False,
            "previous_spot_available": pspot is not None,
            "previous_bid_available": pbid is not None,
            "previous_ask_available": pask is not None,
        },
    }
    with _lock:
        _by_ticker[t] = out
    try:
        from planes.l1_events import notify_quote_updated

        notify_quote_updated(t)
    except Exception as e:
        log.debug("notify_quote_updated: %s", e, exc_info=True)
    return True


def record_quote(ticker: str, payload: dict[str, Any]) -> None:
    """Persist a full plane row (e.g. REST fast-quote). Replaces prior row for ticker."""
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical quote-plane key (write+read consistent; idempotent on Schwab stream symbols)
    if not t:
        return
    with _lock:
        _by_ticker[t] = dict(payload)
    try:
        from planes.l1_events import notify_quote_updated

        notify_quote_updated(t)
    except Exception as e:
        log.debug("notify_quote_updated: %s", e, exc_info=True)


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


def quote_is_fresh(q: dict[str, Any]) -> bool:
    """Is this plane row trustworthy as a LIVE value right now.

    Carried-forward / auth-degraded rows keep their LAST_PRICE number and their
    degradation flags, but they are not LIVE: treating them as fresh made every
    consumer paint an old print as current. Age is the only live gate. A missing
    server_received_ts cannot be assumed fresh (fail closed).
    """
    received = _safe_float(q.get("server_received_ts"))
    if received is None:
        return False
    age = time.time() - received
    return age >= 0.0 and age < PLANE_QUOTE_STALE_SEC


def merge_into_state(ms_dict: dict[str, Any], ticker: str) -> None:
    """
    Tier C only: overlay spot/bid/ask/display fields from the live plane onto an analytical ms_dict.
    Call at end of _fetch_state before return so Layer C payloads carry Layer A truth.

    Does not write to Layer A storage (_by_ticker). For L1 read-path overlay, use
    apply_l1_live_quote_overlay (same field merge, explicit L1 contract).

    A row older than PLANE_QUOTE_STALE_SEC is treated exactly like no row: the caller's own
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
    last_price_spot = plane_spot_is_last_price(q)
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

    A row older than PLANE_QUOTE_STALE_SEC is treated exactly like no row: the cached L1
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
    last_price_spot = plane_spot_is_last_price(q)
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
